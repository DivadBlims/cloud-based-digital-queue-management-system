from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
from werkzeug.utils import secure_filename
import os
import uuid
import threading
from datetime import datetime
from functools import wraps
from models import db, User, File, FileBlock
from storage_virtual_network import StorageVirtualNetwork
from storage_virtual_node import StorageVirtualNode
from block_manager import BlockManager

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cloudsim.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024  # 10GB max file size

# Initialize database
db.init_app(app)

# Initialize storage network
storage_network = StorageVirtualNetwork()
block_manager = BlockManager(storage_network)

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('blocks', exist_ok=True)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            flash('Admin access required', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validation
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('signup.html')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return render_template('signup.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return render_template('signup.html')
        
        # Create user
        user = User(username=username, email=email, storage_limit_gb=5.0)
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    files = File.query.filter_by(user_id=user.id).order_by(File.uploaded_at.desc()).all()
    
    used_gb = user.get_used_storage_gb()
    remaining_gb = user.get_remaining_storage_gb()
    limit_gb = user.storage_limit_gb
    usage_percent = (used_gb / limit_gb * 100) if limit_gb > 0 else 0
    
    return render_template('dashboard.html',
                         user=user,
                         files=files,
                         used_gb=used_gb,
                         remaining_gb=remaining_gb,
                         limit_gb=limit_gb,
                         usage_percent=usage_percent)

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('dashboard'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('dashboard'))
    
    user = User.query.get(session['user_id'])
    
    # Check storage quota
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    if not user.can_store_file(file_size):
        flash(f'Storage quota exceeded. You have {user.get_remaining_storage_gb():.2f} GB remaining.', 'error')
        return redirect(url_for('dashboard'))
    
    # Generate unique file ID
    file_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    
    # Save temporarily
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
    file.save(temp_path)
    
    try:
        # Create file record
        db_file = File(
            file_id=file_id,
            filename=filename,
            file_size=file_size,
            mime_type=file.content_type,
            user_id=user.id
        )
        db.session.add(db_file)
        db.session.commit()
        
        # Distribute blocks across nodes
        if block_manager.distribute_file_blocks(temp_path, db_file, user.id):
            # Refresh node storage from database after upload
            for node in storage_network.nodes.values():
                blocks_on_node = FileBlock.query.filter_by(node_id=node.node_id).all()
                node.used_storage = sum(block.block_size for block in blocks_on_node)
            
            flash(f'File "{filename}" uploaded successfully!', 'success')
        else:
            db.session.delete(db_file)
            db.session.commit()
            flash('Failed to store file blocks. Please try again.', 'error')
    except Exception as e:
        db.session.rollback()
        flash(f'Error uploading file: {str(e)}', 'error')
    finally:
        # Clean up temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    return redirect(url_for('dashboard'))

@app.route('/download/<file_id>')
@login_required
def download_file(file_id):
    user = User.query.get(session['user_id'])
    file = File.query.filter_by(file_id=file_id).first()
    
    if not file:
        flash('File not found', 'error')
        return redirect(url_for('dashboard'))
    
    if file.user_id != user.id:
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    
    # Reconstruct file from blocks
    temp_download_path = os.path.join(app.config['UPLOAD_FOLDER'], f"download_{file_id}")
    
    if not block_manager.reconstruct_file(file, temp_download_path):
        flash('Failed to retrieve file blocks', 'error')
        return redirect(url_for('dashboard'))
    
    # Schedule cleanup after 5 minutes
    def cleanup_file():
        try:
            if os.path.exists(temp_download_path):
                os.remove(temp_download_path)
        except Exception:
            pass
    
    threading.Timer(300.0, cleanup_file).start()  # Clean up after 5 minutes
    
    return send_file(
        temp_download_path,
        as_attachment=True,
        download_name=file.filename
    )

@app.route('/delete/<file_id>', methods=['POST'])
@login_required
def delete_file(file_id):
    user = User.query.get(session['user_id'])
    file = File.query.filter_by(file_id=file_id).first()
    
    if not file:
        flash('File not found', 'error')
        return redirect(url_for('dashboard'))
    
    if file.user_id != user.id:
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    
    # Delete blocks (this also updates node storage)
    block_manager.delete_file_blocks(file)
    
    # Delete file record
    db.session.delete(file)
    db.session.commit()
    
    # Refresh node storage from database after deletion
    for node in storage_network.nodes.values():
        blocks_on_node = FileBlock.query.filter_by(node_id=node.node_id).all()
        node.used_storage = sum(block.block_size for block in blocks_on_node)
    
    flash(f'File "{file.filename}" deleted successfully', 'success')
    return redirect(url_for('dashboard'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    stats = storage_network.get_network_stats(db_session=db.session)
    nodes = list(storage_network.nodes.values())
    
    # Calculate node details with actual storage usage from database
    node_details = []
    for node in nodes:
        # Calculate actual used storage from database blocks
        blocks_on_node = FileBlock.query.filter_by(node_id=node.node_id).all()
        actual_used_storage = sum(block.block_size for block in blocks_on_node)
        
        # Update node's used_storage to match database
        node.used_storage = actual_used_storage
        
        storage_util = (actual_used_storage / node.total_storage * 100) if node.total_storage > 0 else 0
        node_details.append({
            'id': node.node_id,
            'cpu': node.cpu_capacity,
            'memory': node.memory_capacity,
            'storage_total_gb': node.total_storage / (1024**3),
            'storage_used_gb': actual_used_storage / (1024**3),
            'storage_util_percent': storage_util,
            'bandwidth_mbps': node.bandwidth / 1000000
        })
    
    total_users = User.query.count()
    total_files = File.query.count()
    
    return render_template('admin.html',
                         stats=stats,
                         nodes=node_details,
                         total_users=total_users,
                         total_files=total_files)

@app.route('/admin/add_node', methods=['POST'])
@admin_required
def add_node():
    node_id = request.form.get('node_id')
    cpu = int(request.form.get('cpu_capacity'))
    memory = int(request.form.get('memory_capacity'))
    storage = int(request.form.get('storage_capacity'))
    bandwidth = int(request.form.get('bandwidth'))
    
    if node_id in storage_network.nodes:
        flash(f'Node "{node_id}" already exists', 'error')
        return redirect(url_for('admin_dashboard'))
    
    # Create new node
    new_node = StorageVirtualNode(
        node_id=node_id,
        cpu_capacity=cpu,
        memory_capacity=memory,
        storage_capacity=storage,
        bandwidth=bandwidth
    )
    
    # Add to network
    storage_network.add_node(new_node)
    
    # Connect to existing nodes (simple full mesh)
    for existing_node_id in storage_network.nodes.keys():
        if existing_node_id != node_id:
            storage_network.connect_nodes(node_id, existing_node_id, min(bandwidth, 1000))
    
    # Create blocks directory for new node
    node_dir = os.path.join('blocks', node_id)
    os.makedirs(node_dir, exist_ok=True)
    
    flash(f'Node "{node_id}" added successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/extend_node', methods=['POST'])
@admin_required
def extend_node():
    node_id = request.form.get('node_id')
    additional_storage_gb = int(request.form.get('additional_storage'))
    
    if node_id not in storage_network.nodes:
        flash('Node not found', 'error')
        return redirect(url_for('admin_dashboard'))
    
    node = storage_network.nodes[node_id]
    additional_bytes = additional_storage_gb * 1024 * 1024 * 1024
    node.total_storage += additional_bytes
    
    flash(f'Extended storage for node "{node_id}" by {additional_storage_gb} GB', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_node', methods=['POST'])
@admin_required
def delete_node():
    node_id = request.form.get('node_id')
    
    if node_id not in storage_network.nodes:
        flash('Node not found', 'error')
        return redirect(url_for('admin_dashboard'))
    
    # Check if node has stored blocks
    node = storage_network.nodes[node_id]
    if node.used_storage > 0:
        flash(f'Cannot delete node "{node_id}" - it contains {node.used_storage / (1024**3):.2f} GB of data. Please migrate data first.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    # Remove node directory
    node_dir = os.path.join('blocks', node_id)
    if os.path.exists(node_dir):
        try:
            import shutil
            shutil.rmtree(node_dir)
        except Exception as e:
            flash(f'Warning: Could not delete node directory: {str(e)}', 'error')
    
    # Remove from network
    del storage_network.nodes[node_id]
    
    # Remove connections
    for other_node in storage_network.nodes.values():
        if node_id in other_node.connections:
            del other_node.connections[node_id]
    
    flash(f'Node "{node_id}" deleted successfully', 'success')
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Create default admin user if doesn't exist
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', email='admin@blimsphere.com', is_admin=True, storage_limit_gb=100.0)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
        
        # Initialize default nodes if network is empty
        if len(storage_network.nodes) == 0:
            node1 = StorageVirtualNode("node1", cpu_capacity=4, memory_capacity=16, storage_capacity=500, bandwidth=1000)
            node2 = StorageVirtualNode("node2", cpu_capacity=8, memory_capacity=32, storage_capacity=1000, bandwidth=2000)
            storage_network.add_node(node1)
            storage_network.add_node(node2)
            storage_network.connect_nodes("node1", "node2", bandwidth=1000)
            
            # Create block directories
            os.makedirs('blocks/node1', exist_ok=True)
            os.makedirs('blocks/node2', exist_ok=True)
        
        # Initialize node storage from database
        for node in storage_network.nodes.values():
            blocks_on_node = FileBlock.query.filter_by(node_id=node.node_id).all()
            node.used_storage = sum(block.block_size for block in blocks_on_node)
    
    app.run(debug=True, host='0.0.0.0', port=5000)

