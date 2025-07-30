import os
import pandas as pd
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from werkzeug.utils import secure_filename
from contextlib import contextmanager
from chatbot_model import get_chat_response

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'db'}  # Added xlsx support
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = 'your_secret_key_here'  # Required for flash messages

# Initialize DB
DB_FILE = 'chatbot_data.db'

# Database connection helper
@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    try:
        yield conn
    finally:
        conn.close()

# Initialize database tables
with get_db_connection() as conn:
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_history (id INTEGER PRIMARY KEY, message TEXT, response TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS current_file (id INTEGER PRIMARY KEY, filename TEXT)''')
    conn.commit()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_current_file():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT filename FROM current_file ORDER BY id DESC LIMIT 1")
        result = cursor.fetchone()
        return result[0] if result else None

def set_current_file(filename):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM current_file")
        cursor.execute("INSERT INTO current_file (filename) VALUES (?)", (filename,))
        conn.commit()

def clear_current_file():
    """Clear the current file reference from database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM current_file")
        conn.commit()

def read_data_file(file_path):
    """Read data file (CSV or Excel) with proper error handling"""
    file_ext = file_path.rsplit('.', 1)[1].lower()
    
    try:
        if file_ext == 'csv':
            # Try different encodings for CSV
            try:
                return pd.read_csv(file_path)
            except UnicodeDecodeError:
                return pd.read_csv(file_path, encoding='latin1')
        elif file_ext == 'xlsx':
            return pd.read_excel(file_path)
        else:
            raise ValueError(f"Unsupported file format: {file_ext}")
    except Exception as e:
        raise Exception(f"Error reading {file_ext.upper()} file: {str(e)}")

@app.route('/')
def index():
    current_file = get_current_file()
    
    # Get chat history
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT message, response FROM chat_history")
        history = cursor.fetchall()
    
    # Get flash messages if any
    error = request.args.get('error')
    return render_template('index.html', history=history, filename=current_file, error=error)

@app.route('/ask', methods=['POST'])
def ask():
    user_input = request.json.get('message')
    current_file = get_current_file()
    
    if not current_file:
        return jsonify({'response': '⚠️ No dataset available. Please upload a CSV or Excel file first.'})
    
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], current_file)
    
    try:
        df = read_data_file(file_path)
            
        # Check if dataframe is empty
        if df.empty:
            return jsonify({'response': 'Error: The uploaded file is empty.'})
            
    except Exception as e:
        return jsonify({'response': f'Error reading file: {str(e)}'})
    
    response = get_chat_response(user_input, df)
    
    # Save to DB
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO chat_history (message, response) VALUES (?, ?)", (user_input, response))
        conn.commit()
    
    return jsonify({'response': response})

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('index'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('index'))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Validate the data file
        try:
            test_df = read_data_file(file_path)
            if test_df.empty:
                os.remove(file_path)  # Remove invalid file
                clear_current_file()  # Clear current file reference
                flash('Uploaded file is empty', 'error')
                return redirect(url_for('index'))
        except Exception as e:
            if os.path.exists(file_path):
                os.remove(file_path)  # Remove invalid file
            clear_current_file()  # Clear current file reference
            flash(f'Invalid file format: {str(e)}', 'error')
            return redirect(url_for('index'))
        
        set_current_file(filename)
        
        # Clear chat history
        with get_db_connection() as conn:
            conn.execute("DELETE FROM chat_history")
            conn.commit()
        
        flash('File uploaded successfully!', 'success')
    else:
        clear_current_file()  # Clear current file reference
        flash('Invalid file type. Please upload a CSV or Excel file (.xlsx)', 'error')
    
    return redirect(url_for('index'))

@app.route('/delete_file', methods=['POST'])
def delete_file():
    current_file = get_current_file()
    
    if current_file:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], current_file)
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Clear file + chat history
        clear_current_file()
        with get_db_connection() as conn:
            conn.execute("DELETE FROM chat_history")
            conn.commit()
        
        flash('File deleted successfully', 'success')
    else:
        flash('No file to delete', 'error')
    
    return redirect(url_for('index'))

@app.route('/clear_chat', methods=['POST'])
def clear_chat():
    with get_db_connection() as conn:
        conn.execute("DELETE FROM chat_history")
        conn.commit()
    
    return jsonify({'status': 'cleared'})

if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)