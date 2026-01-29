from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import time
import pytz

app = Flask(__name__)
CORS(app)

# 配置数据库
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gas_stock.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 数据库模型
class StockRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(10), nullable=False)  # in 或 out
    weight = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    unit = db.Column(db.String(10), nullable=False)  # kg 或 jin

class StockSummary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    current_stock = db.Column(db.Float, default=0)  # 公斤
    total_sales = db.Column(db.Float, default=0)  # 总销售额
    total_cost = db.Column(db.Float, default=0)  # 总成本

# 初始化数据库
with app.app_context():
    db.create_all()
    # 检查是否存在库存记录，不存在则创建
    if StockSummary.query.count() == 0:
        summary = StockSummary(current_stock=0, total_sales=0, total_cost=0)
        db.session.add(summary)
        db.session.commit()

# API接口
@app.route('/api/stock/in', methods=['POST'])
def stock_in():
    data = request.get_json()
    weight = data.get('weight')
    amount = data.get('amount')
    
    if not weight or not amount:
        return jsonify({'error': '缺少必要参数'}), 400
    
    # 创建入库记录
    record = StockRecord(
        type='in',
        weight=weight,
        amount=amount,
        unit='kg'
    )
    db.session.add(record)
    
    # 更新库存和成本
    summary = StockSummary.query.first()
    summary.current_stock += weight
    summary.total_cost += amount
    db.session.commit()
    
    return jsonify({'success': True, 'message': '入库成功'})

@app.route('/api/stock/out', methods=['POST'])
def stock_out():
    data = request.get_json()
    weight = data.get('weight')  # 斤
    amount = data.get('amount')
    
    if not weight or not amount:
        return jsonify({'error': '缺少必要参数'}), 400
    
    # 转换为公斤
    weight_kg = weight / 2
    
    # 检查库存
    summary = StockSummary.query.first()
    if summary.current_stock < weight_kg:
        return jsonify({'error': '库存不足'}), 400
    
    # 创建出库记录
    record = StockRecord(
        type='out',
        weight=weight,
        amount=amount,
        unit='jin'
    )
    db.session.add(record)
    
    # 更新库存和销售额
    summary.current_stock -= weight_kg
    summary.total_sales += amount
    db.session.commit()
    
    return jsonify({'success': True, 'message': '出库成功'})

@app.route('/api/stock/summary', methods=['GET'])
def get_summary():
    summary = StockSummary.query.first()
    profit = summary.total_sales - summary.total_cost  # 计算盈利
    return jsonify({
        'current_stock': summary.current_stock,
        'total_sales': summary.total_sales,
        'total_cost': summary.total_cost,
        'profit': profit
    })

@app.route('/api/stock/records', methods=['GET'])
def get_records():
    # 获取时间范围参数
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    
    # 构建查询
    query = StockRecord.query
    
    # 应用时间范围过滤
    if start_time:
        # 转换为UTC时间
        start_utc = datetime.strptime(start_time, '%Y-%m-%d').replace(tzinfo=pytz.timezone('Asia/Shanghai')).astimezone(pytz.utc)
        query = query.filter(StockRecord.created_at >= start_utc)
    
    if end_time:
        # 转换为UTC时间（加一天，包含结束日期）
        end_utc = datetime.strptime(end_time, '%Y-%m-%d').replace(tzinfo=pytz.timezone('Asia/Shanghai')).astimezone(pytz.utc)
        end_utc = end_utc.replace(hour=23, minute=59, second=59, microsecond=999999)
        query = query.filter(StockRecord.created_at <= end_utc)
    
    # 按时间倒序排序
    records = query.order_by(StockRecord.created_at.desc()).all()
    
    result = []
    # 获取本地时区
    local_tz = pytz.timezone('Asia/Shanghai')
    for record in records:
        # 将UTC时间转换为本地时间
        local_time = record.created_at.replace(tzinfo=pytz.utc).astimezone(local_tz)
        result.append({
            'id': record.id,
            'type': '入库' if record.type == 'in' else '出库',
            'weight': record.weight,
            'unit': '公斤' if record.unit == 'kg' else '斤',
            'amount': record.amount,
            'created_at': local_time.strftime('%Y-%m-%d %H:%M:%S')
        })
    return jsonify(result)

@app.route('/api/stock/records/<int:record_id>', methods=['DELETE'])
def delete_record(record_id):
    record = StockRecord.query.get(record_id)
    if not record:
        return jsonify({'error': '记录不存在'}), 404
    
    # 更新库存
    summary = StockSummary.query.first()
    if record.type == 'in':
        summary.current_stock -= record.weight
        summary.total_cost -= record.amount
    else:
        # 出库记录，转换为公斤
        weight_kg = record.weight / 2
        summary.current_stock += weight_kg
        summary.total_sales -= record.amount
    
    db.session.delete(record)
    db.session.commit()
    return jsonify({'success': True, 'message': '记录删除成功'})

@app.route('/api/stock/records/<int:record_id>', methods=['PUT'])
def update_record(record_id):
    record = StockRecord.query.get(record_id)
    if not record:
        return jsonify({'error': '记录不存在'}), 404
    
    data = request.get_json()
    weight = data.get('weight')
    amount = data.get('amount')
    
    if not weight or not amount:
        return jsonify({'error': '缺少必要参数'}), 400
    
    # 更新库存
    summary = StockSummary.query.first()
    if record.type == 'in':
        summary.current_stock -= record.weight
        summary.total_cost -= record.amount
        summary.current_stock += weight
        summary.total_cost += amount
    else:
        # 出库记录，转换为公斤
        old_weight_kg = record.weight / 2
        new_weight_kg = weight / 2
        summary.current_stock += old_weight_kg
        summary.total_sales -= record.amount
        summary.current_stock -= new_weight_kg
        summary.total_sales += amount
    
    # 更新记录
    record.weight = weight
    record.amount = amount
    db.session.commit()
    return jsonify({'success': True, 'message': '记录更新成功'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
