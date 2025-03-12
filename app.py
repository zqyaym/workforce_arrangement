from flask import Flask, request, jsonify, send_file, render_template, url_for
import os
import csv
import chardet
import uuid
import shutil
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 启用跨域请求支持

# 配置参数
UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
ALLOWED_EXTENSIONS = {'csv'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# 创建必要的目录
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

# 文件有效期跟踪
file_expiry = {}

# 辅助函数：检查文件扩展名是否允许
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 辅助函数：检测文件编码
def detect_encoding(file_path):
    with open(file_path, 'rb') as f:
        result = chardet.detect(f.read())
    return result['encoding']

# 辅助函数：处理CSV文件
def process_csv(input_path, output_path):
    try:
        # 检测编码
        encoding = detect_encoding(input_path)
        if encoding.lower() != 'utf-8':
            return False, "文件编码不是UTF-8，请转换后重试"
        
        # 读取CSV并处理数据
        total_sum = 0
        data_rows = []
        
        with open(input_path, 'r', encoding='utf-8') as f:
            csv_reader = csv.reader(f)
            header = next(csv_reader, None)  # 获取表头
            
            if not header:
                return False, "CSV文件格式错误：没有表头"
            
            data_rows.append(header)  # 保存表头
            
            for row in csv_reader:
                if len(row) >= 2:  # 确保至少有两列
                    try:
                        # 尝试将第二列转换为数字并累加
                        value = float(row[1])
                        total_sum += value
                    except (ValueError, IndexError):
                        # 如果转换失败，跳过该行
                        pass
                data_rows.append(row)  # 保存所有行数据
        
        # 创建新的CSV文件，在B1单元格写入合计值
        with open(output_path, 'w', encoding='utf-8', newline='') as f:
            csv_writer = csv.writer(f)
            
            # 写入表头
            csv_writer.writerow(data_rows[0])
            
            # 在B1单元格写入合计值（即第一行的第二列）
            if len(data_rows) > 1:
                first_row = data_rows[1]
                if len(first_row) >= 2:
                    first_row[1] = total_sum
                csv_writer.writerow(first_row)
                
                # 写入剩余行
                for row in data_rows[2:]:
                    csv_writer.writerow(row)
            
        return True, "处理成功"
    except Exception as e:
        return False, f"处理CSV文件时出错: {str(e)}"

# 路由：主页
@app.route('/')
def index():
    return render_template('index.html')

# 路由：上传文件
@app.route('/upload', methods=['POST'])
def upload_file():
    # 检查是否有文件
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '没有文件部分'}), 400
    
    file = request.files['file']
    
    # 检查文件名
    if file.filename == '':
        return jsonify({'success': False, 'message': '没有选择文件'}), 400
    
    # 检查文件大小
    if request.content_length > MAX_FILE_SIZE:
        return jsonify({'success': False, 'message': f'文件大小超过限制（最大{MAX_FILE_SIZE/1024/1024}MB）'}), 400
    
    # 检查文件类型
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': '只允许上传CSV文件'}), 400
    
    # 保存文件
    filename = secure_filename(file.filename)
    unique_id = str(uuid.uuid4())
    original_path = os.path.join(UPLOAD_FOLDER, f"{unique_id}_{filename}")
    file.save(original_path)
    
    # 处理文件
    processed_filename = f"processed_{unique_id}_{filename}"
    processed_path = os.path.join(PROCESSED_FOLDER, processed_filename)
    
    success, message = process_csv(original_path, processed_path)
    
    if not success:
        # 删除上传的文件
        os.remove(original_path)
        if os.path.exists(processed_path):
            os.remove(processed_path)
        return jsonify({'success': False, 'message': message}), 400
    
    # 设置文件过期时间（30分钟后）
    expiry_time = datetime.now() + timedelta(minutes=30)
    file_expiry[processed_filename] = expiry_time
    
    # 返回成功响应
    return jsonify({
        'success': True, 
        'message': '文件处理成功', 
        'filename': processed_filename,
        'download_url': url_for('download_file', filename=processed_filename)
    })

# 路由：下载文件
@app.route('/download/<filename>')
def download_file(filename):
    # 检查文件是否存在
    file_path = os.path.join(PROCESSED_FOLDER, filename)
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'message': '文件不存在或已过期'}), 404
    
    # 检查文件是否过期
    if filename in file_expiry:
        if datetime.now() > file_expiry[filename]:
            # 删除过期文件
            os.remove(file_path)
            del file_expiry[filename]
            return jsonify({'success': False, 'message': '文件已过期'}), 404
    
    # 发送文件
    return send_file(file_path, as_attachment=True, download_name=filename.split('_', 2)[2])

# 定期清理过期文件的函数（在实际应用中可以使用定时任务）
def cleanup_expired_files():
    current_time = datetime.now()
    expired_files = []
    
    for filename, expiry_time in file_expiry.items():
        if current_time > expiry_time:
            file_path = os.path.join(PROCESSED_FOLDER, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
            expired_files.append(filename)
    
    # 从字典中删除过期文件
    for filename in expired_files:
        del file_expiry[filename]

# 启动应用
if __name__ == '__main__':
    # 启动前清理临时文件
    for folder in [UPLOAD_FOLDER, PROCESSED_FOLDER]:
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
    
    app.run(debug=True, host='0.0.0.0', port=5000)