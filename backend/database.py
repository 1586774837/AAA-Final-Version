from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import paramiko
import re
import time
import threading
import json
import os
import random

# === 数据库操作 ===
def get_db():
    conn = sqlite3.connect('/app/data/monitor.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hosts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            port INTEGER DEFAULT 22,
            name TEXT,
            host_type TEXT DEFAULT 'real',  -- real: 真实主机, simulated: 模拟主机
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL,
            cpu_usage REAL,
            memory_usage REAL,
            memory_total REAL,
            memory_used REAL,
            disk_usage REAL,
            load_avg TEXT,
            data_source TEXT DEFAULT 'real',  -- real: 真实数据, simulated: 模拟数据
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES hosts (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def add_host(ip, username, password, port=22, name="", host_type="real"):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO hosts (ip, username, password, port, name, host_type) VALUES (?, ?, ?, ?, ?, ?)',
                   (ip, username, password, port, name, host_type))
    host_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return host_id

def delete_host(host_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM metrics WHERE host_id = ?', (host_id,))
    cursor.execute('DELETE FROM hosts WHERE id = ?', (host_id,))
    conn.commit()
    conn.close()

def get_all_hosts():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM hosts ORDER BY created_at DESC')
    hosts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return hosts

def save_metrics(host_id, metrics, data_source="real"):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO metrics 
        (host_id, cpu_usage, memory_usage, memory_total, memory_used, disk_usage, load_avg, data_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        host_id,
        metrics.get('cpu_usage'),
        metrics.get('memory_usage'),
        metrics.get('memory_total'),
        metrics.get('memory_used'),
        metrics.get('disk_usage'),
        json.dumps(metrics.get('load_avg', [])),
        data_source
    ))
    conn.commit()
    conn.close()

    # === 调度器 ===
def start_scheduler():
    def collection_loop():
        while True:
            try:
                hosts = get_all_hosts()
                print(f"开始采集周期，共 {len(hosts)} 台主机")

                for host in hosts:
                    try:
                        metrics = collect_host_metrics(host)
                        if metrics:
                            # 确定数据来源
                            data_source = 'simulated' if host.get('host_type') == 'simulated' else 'real'
                            save_metrics(host['id'], metrics, data_source)

                            realtime_metrics[host['id']] = {
                                **metrics,
                                'last_update': time.time(),
                                'status': 'online',
                                'data_source': data_source,
                                'host_type': host.get('host_type', 'real')
                            }
                            print(f"主机 {host['ip']} 采集成功 ({data_source}数据)")
                        else:
                            realtime_metrics[host['id']] = {
                                'status': 'offline',
                                'error': '采集失败'
                            }
                            print(f"主机 {host['ip']} 采集失败")
                    except Exception as e:
                        print(f"采集主机 {host['ip']} 异常: {str(e)}")
                        realtime_metrics[host['id']] = {
                            'status': 'offline',
                            'error': str(e)
                        }

                print(f"采集周期完成，等待30秒")
                time.sleep(30)
            except Exception as e:
                print(f"调度器错误: {str(e)}")
                time.sleep(10)

    thread = threading.Thread(target=collection_loop, daemon=True)
    thread.start()
