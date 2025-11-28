from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import paramiko
import re
import time
import threading
import json
import os
import random

app = Flask(__name__)

# === 前端服务 ===
@app.route('/')
def index():
    """服务主页"""
    try:
        with open('/app/frontend/index.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return """
        <html>
            <head><title>服务器监控系统</title></head>
            <body>
                <h1>服务器监控系统</h1>
                <p>前端文件未找到，但后端 API 正常工作</p>
                <p><a href="/health">检查健康状态</a></p>
                <p><a href="/api/hosts">查看主机 API</a></p>
            </body>
        </html>
        """, 200

@app.route('/dashboard')
def dashboard():
    """服务监控大屏"""
    try:
        with open('/app/frontend/dashboard.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return """
        <html>
            <head><title>监控大屏</title></head>
            <body>
                <h1>监控大屏</h1>
                <p>前端文件未找到，但后端 API 正常工作</p>
                <p><a href="/">返回主页</a></p>
            </body>
        </html>
        """, 200

@app.route('/<path:filename>')
def serve_static(filename):
    """服务静态文件"""
    static_dirs = {
        'css': 'css',
        'js': 'js', 
        'lib': 'lib'
    }
    
    file_type = filename.split('/')[0] if '/' in filename else None
    
    if file_type in static_dirs:
        try:
            return send_from_directory(f'/app/frontend/{static_dirs[file_type]}', filename[len(file_type)+1:])
        except FileNotFoundError:
            return f"Static file {filename} not found", 404
    else:
        return "File not found", 404



# === API路由 ===
# 获取所有主机
@app.route('/api/hosts', methods=['GET'])
def get_hosts():
    return jsonify(get_all_hosts())

# 添加新主机
@app.route('/api/hosts', methods=['POST'])
def create_host():
    data = request.json
    print("添加主机:", data)
    
    required_fields = ['ip', 'username', 'password']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'缺少字段: {field}'}), 400
    
    try:
        host_type = data.get('host_type', 'real')
        host_id = add_host(
            data['ip'],
            data['username'],
            data['password'],
            data.get('port', 22),
            data.get('name', ''),
            host_type
        )
        return jsonify({'id': host_id, 'message': '主机添加成功'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 删除主机
@app.route('/api/hosts/<int:host_id>', methods=['DELETE'])
def remove_host(host_id):
    try:
        delete_host(host_id)
        if host_id in realtime_metrics:
            del realtime_metrics[host_id]
        return jsonify({'message': '主机删除成功'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# 获取实时监控数据
@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    return jsonify(realtime_metrics)

# 测试主机连接
@app.route('/api/test-connection/<int:host_id>', methods=['POST'])
def test_connection(host_id):
    """测试主机连接"""
    try:
        hosts = get_all_hosts()
        host = next((h for h in hosts if h['id'] == host_id), None)
        if not host:
            return jsonify({'success': False, 'error': '主机未找到'})
        
        host_type = host.get('host_type', 'real')
        
        if host_type == 'simulated':
            # 模拟主机：直接返回成功
            return jsonify({
                'success': True,
                'message': '模拟主机连接测试成功',
                'host_type': 'simulated'
            })
        else:
            # 真实主机：测试SSH连接
            print(f"测试SSH连接: {host['ip']}")
            real_metrics = collect_real_metrics(host)
            if real_metrics:
                return jsonify({
                    'success': True,
                    'message': 'SSH连接成功',
                    'host_type': 'real',
                    'metrics': real_metrics
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'SSH连接失败',
                    'host_type': 'real'
                })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# 立即采集主机数据
@app.route('/api/collect-now/<int:host_id>', methods=['POST'])
def collect_now(host_id):
    """立即采集主机数据"""
    try:
        hosts = get_all_hosts()
        host = next((h for h in hosts if h['id'] == host_id), None)
        if not host:
            return jsonify({'success': False, 'error': '主机未找到'})
        
        metrics = collect_host_metrics(host)
        if metrics:
            data_source = 'simulated' if host.get('host_type') == 'simulated' else 'real'
            save_metrics(host_id, metrics, data_source)
            
            realtime_metrics[host_id] = {
                **metrics,
                'last_update': time.time(),
                'status': 'online',
                'data_source': data_source,
                'host_type': host.get('host_type', 'real')
            }
            
            return jsonify({
                'success': True,
                'message': f'采集成功 ({data_source}数据)',
                'metrics': metrics,
                'data_source': data_source
            })
        else:
            return jsonify({'success': False, 'error': '采集失败'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# 添加模拟主机
@app.route('/api/add-simulated-host', methods=['POST'])
def add_simulated_host():
    """添加模拟主机"""
    data = request.json
    name = data.get('name', f'模拟主机-{int(time.time())}')
    
    # 生成唯一的模拟IP
    existing_hosts = get_all_hosts()
    simulated_count = len([h for h in existing_hosts if h.get('host_type') == 'simulated'])
    simulated_ip = f"127.0.0.{100 + simulated_count}"
    
    try:
        host_id = add_host(
            ip=simulated_ip,
            username='simulated',
            password='simulated',
            port=22,
            name=name,
            host_type='simulated'
        )
        
        # 立即生成初始数据
        metrics = generate_simulated_metrics(host_id)
        save_metrics(host_id, metrics, 'simulated')
        realtime_metrics[host_id] = {
            **metrics,
            'last_update': time.time(),
            'status': 'online',
            'data_source': 'simulated',
            'host_type': 'simulated'
        }
        
        return jsonify({
            'success': True,
            'message': '模拟主机添加成功',
            'host': {
                'id': host_id,
                'ip': simulated_ip,
                'name': name,
                'host_type': 'simulated'
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
  
# 健康检查
@app.route('/health')
def health_check():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        return jsonify({'status': 'healthy', 'database': 'connected'})
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500
