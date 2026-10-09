# 校园美食爬虫与AI探店项目
## 项目简介
本项目实现网页美食信息爬虫，抓取餐饮店铺信息，保存至CSV文件；支持关键词检索店铺；调用大模型生成探店文案。
本项目仅使用CPU运行，**不需要AMD ROCm显卡**。

## 文件结构
- main.py：程序入口
- campus_food.py：爬虫、数据处理、AI生成核心业务代码
- requirements.txt：Python依赖库清单
- campus_food_base.csv：输出样例数据文件

## 环境安装
1. Python >=3.10
2. 安装依赖：
```bash
pip install -r requirements.txt
运行步骤
 
1. 运行 main.py
2. 爬虫抓取店铺数据，自动保存csv文件
3. 调用search_food函数，输入关键词检索美食
4. 调用AI模块生成探店描述
 
项目局限与改进方向
 
1. 爬虫容易受网站反爬策略限制
2. 视觉/文本模型推理速度受CPU性能影响
3. 后续可以接入GPU加速提升推理速度
