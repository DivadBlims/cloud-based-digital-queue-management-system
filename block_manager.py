import os
import hashlib
import math
from typing import List, Dict, Tuple, Optional
from models import FileBlock, File, db
from storage_virtual_network import StorageVirtualNetwork
from virtual_disk import VirtualDiskManager

class BlockManager:
    """Manages file block distribution and reconstruction"""
    
    BLOCK_SIZE = 1024 * 1024  # 1MB blocks
    REPLICATION_FACTOR = 2  # Store each block on 2 nodes
    
    def __init__(self, network: StorageVirtualNetwork, blocks_dir: str = "blocks", use_virtual_disk: bool = True):
        self.network = network
        self.blocks_dir = blocks_dir
        self.use_virtual_disk = use_virtual_disk
        self._ensure_blocks_directory()
        
        # Initialize virtual disk manager if enabled
        if self.use_virtual_disk:
            self.vdisk_manager = VirtualDiskManager()
            # Create virtual disks for all nodes
            for node_id in self.network.nodes.keys():
                node = self.network.nodes[node_id]
                disk_size_gb = node.total_storage / (1024 ** 3)
                self.vdisk_manager.create_node_disk(node_id, disk_size_gb)
    
    def _ensure_blocks_directory(self):
        """Create blocks directory structure for each node"""
        if not os.path.exists(self.blocks_dir):
            os.makedirs(self.blocks_dir)
        
        for node_id in self.network.nodes.keys():
            node_dir = os.path.join(self.blocks_dir, node_id)
            if not os.path.exists(node_dir):
                os.makedirs(node_dir)
    
    def split_file_into_blocks(self, file_path: str, file_id: str) -> List[Tuple[bytes, str]]:
        """
        Split file into blocks and calculate checksums
        Returns: List of (block_data, checksum) tuples
        """
        blocks = []
        block_index = 0
        
        with open(file_path, 'rb') as f:
            while True:
                block_data = f.read(self.BLOCK_SIZE)
                if not block_data:
                    break
                
                checksum = hashlib.md5(block_data).hexdigest()
                blocks.append((block_data, checksum))
                block_index += 1
        
        return blocks
    
    def select_nodes_for_block(self, block_id: int, num_replicas: int = None) -> List[str]:
        """
        Select nodes to store a block (with replication)
        Returns list of node IDs
        """
        if num_replicas is None:
            num_replicas = self.REPLICATION_FACTOR
        
        available_nodes = list(self.network.nodes.keys())
        if len(available_nodes) == 0:
            return []
        
        # Simple round-robin with offset based on block_id for distribution
        selected = []
        for i in range(min(num_replicas, len(available_nodes))):
            node_index = (block_id + i) % len(available_nodes)
            selected.append(available_nodes[node_index])
        
        return selected
    
    def store_block(self, block_data: bytes, node_id: str, file_id: str, block_id: int) -> str:
        """
        Store a block on a specific node
        Uses virtual disk if enabled, otherwise uses file system
        Returns: path to stored block or block identifier
        """
        block_identifier = f"{file_id}_block_{block_id}"
        
        if self.use_virtual_disk and hasattr(self, 'vdisk_manager'):
            # Store in virtual disk
            success = self.vdisk_manager.store_block_in_disk(node_id, block_data, block_identifier)
            if success:
                return f"vdisk://{node_id}/{block_identifier}"
        
        # Fallback to file system storage
        node_dir = os.path.join(self.blocks_dir, node_id)
        block_filename = f"{file_id}_block_{block_id}.dat"
        block_path = os.path.join(node_dir, block_filename)
        
        with open(block_path, 'wb') as f:
            f.write(block_data)
        
        return block_path
    
    def retrieve_block(self, node_id: str, file_id: str, block_id: int) -> Optional[bytes]:
        """
        Retrieve a block from a node
        Uses virtual disk if enabled, otherwise uses file system
        Returns: block data or None if not found
        """
        block_identifier = f"{file_id}_block_{block_id}"
        
        if self.use_virtual_disk and hasattr(self, 'vdisk_manager'):
            # Try to retrieve from virtual disk
            data = self.vdisk_manager.retrieve_block_from_disk(node_id, block_identifier)
            if data:
                return data
        
        # Fallback to file system storage
        node_dir = os.path.join(self.blocks_dir, node_id)
        block_filename = f"{file_id}_block_{block_id}.dat"
        block_path = os.path.join(node_dir, block_filename)
        
        if not os.path.exists(block_path):
            return None
        
        try:
            with open(block_path, 'rb') as f:
                return f.read()
        except Exception:
            return None
    
    def distribute_file_blocks(
        self,
        file_path: str,
        file: File,
        user_id: int
    ) -> bool:
        """
        Distribute file blocks across nodes with replication
        Returns: True if successful
        """
        # Split file into blocks
        blocks_data = self.split_file_into_blocks(file_path, file.file_id)
        
        if len(blocks_data) == 0:
            return False
        
        # Check if nodes have enough storage
        total_size_needed = sum(len(block[0]) for block in blocks_data) * self.REPLICATION_FACTOR
        available_storage = sum(
            node.total_storage - node.used_storage 
            for node in self.network.nodes.values()
        )
        
        if total_size_needed > available_storage:
            return False
        
        # Store each block on multiple nodes
        for block_id, (block_data, checksum) in enumerate(blocks_data):
            # Select nodes for this block
            node_ids = self.select_nodes_for_block(block_id)
            
            if not node_ids:
                return False
            
            # Store primary block
            primary_node = node_ids[0]
            block_path = self.store_block(block_data, primary_node, file.file_id, block_id)
            
            # Create database record for primary block
            primary_block = FileBlock(
                block_id=block_id,
                file_id=file.id,
                node_id=primary_node,
                block_size=len(block_data),
                checksum=checksum,
                is_replica=False,
                data_path=block_path
            )
            db.session.add(primary_block)
            
            # Update node storage
            node = self.network.nodes[primary_node]
            node.used_storage += len(block_data)
            
            # Store replicas
            for replica_idx, replica_node_id in enumerate(node_ids[1:], 1):
                replica_path = self.store_block(block_data, replica_node_id, file.file_id, block_id)
                
                replica_block = FileBlock(
                    block_id=block_id,
                    file_id=file.id,
                    node_id=replica_node_id,
                    block_size=len(block_data),
                    checksum=checksum,
                    is_replica=True,
                    replica_of_block_id=block_id,
                    data_path=replica_path
                )
                db.session.add(replica_block)
                
                # Update replica node storage
                replica_node = self.network.nodes[replica_node_id]
                replica_node.used_storage += len(block_data)
        
        db.session.commit()
        return True
    
    def reconstruct_file(
        self,
        file: File,
        output_path: str
    ) -> bool:
        """
        Reconstruct file from blocks stored across nodes
        Returns: True if successful
        """
        # Get all blocks for this file, ordered by block_id
        blocks = FileBlock.query.filter_by(
            file_id=file.id,
            is_replica=False
        ).order_by(FileBlock.block_id).all()
        
        if not blocks:
            return False
        
        try:
            with open(output_path, 'wb') as output_file:
                for block in blocks:
                    # Try to retrieve block from primary node
                    block_data = self.retrieve_block(block.node_id, file.file_id, block.block_id)
                    
                    # If primary fails, try replicas
                    if block_data is None:
                        replicas = FileBlock.query.filter_by(
                            file_id=file.id,
                            block_id=block.block_id,
                            is_replica=True
                        ).all()
                        
                        for replica in replicas:
                            block_data = self.retrieve_block(replica.node_id, file.file_id, block.block_id)
                            if block_data:
                                break
                    
                    if block_data is None:
                        return False
                    
                    # Verify checksum
                    calculated_checksum = hashlib.md5(block_data).hexdigest()
                    if calculated_checksum != block.checksum:
                        # Try replicas if checksum doesn't match
                        replicas = FileBlock.query.filter_by(
                            file_id=file.id,
                            block_id=block.block_id,
                            is_replica=True
                        ).all()
                        
                        found_valid = False
                        for replica in replicas:
                            replica_data = self.retrieve_block(replica.node_id, file.file_id, block.block_id)
                            if replica_data:
                                replica_checksum = hashlib.md5(replica_data).hexdigest()
                                if replica_checksum == replica.checksum:
                                    block_data = replica_data
                                    found_valid = True
                                    break
                        
                        if not found_valid:
                            return False
                    
                    output_file.write(block_data)
            
            return True
        except Exception as e:
            print(f"Error reconstructing file: {e}")
            return False
    
    def delete_file_blocks(self, file: File) -> bool:
        """Delete all blocks for a file"""
        blocks = FileBlock.query.filter_by(file_id=file.id).all()
        
        for block in blocks:
            # Delete physical block file
            if block.data_path and os.path.exists(block.data_path):
                try:
                    os.remove(block.data_path)
                except Exception:
                    pass
            
            # Update node storage
            if block.node_id in self.network.nodes:
                node = self.network.nodes[block.node_id]
                node.used_storage = max(0, node.used_storage - block.block_size)
            
            # Delete database record
            db.session.delete(block)
        
        db.session.commit()
        return True

