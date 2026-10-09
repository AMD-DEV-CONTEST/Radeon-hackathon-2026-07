import requests
from bs4 import BeautifulSoup
import jieba
import json
import ast
import pandas as pd
from transformers import pipeline
from flask import Flask, request, jsonify

# ---------------------- 1. 校园美食数据爬取模块 ----------------------
class CampusFoodCrawler:
    def __init__(self, campus_name):
        self.campus_name = campus_name
        self.food_data = []
    
    def fetch_meituan_reviews(self, url):
        """爬取校园周边美食点评基础信息"""
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 解析店铺信息
        for shop in soup.select(".shop-item"):
            shop_info = {
                "name": shop.select_one(".shop-name").text.strip(),
                "location": shop.select_one(".shop-addr").text.strip(),
                "score": shop.select_one(".shop-score").text.strip(),
                "tags": [tag.text.strip() for tag in shop.select(".tag-item")],
                "price": shop.select_one(".avg-price").text.strip()
            }
            self.food_data.append(shop_info)
    
    def save_to_knowledge_base(self, save_path="campus_food_base.csv"):
        """将采集的数据存入本地知识库"""
        df = pd.DataFrame(self.food_data)
        df.to_csv(save_path, index=False, encoding="utf-8-sig")
        print(f"已成功写入{len(self.food_data)}条美食数据到知识库")

# ---------------------- 2. 本地美食知识库模块 ----------------------
class FoodKnowledgeBase:
    def __init__(self, data_path="campus_food_base.csv"):
        self.data = pd.read_csv(data_path, encoding="utf-8-sig",dtype=str)
        print("列名: ",self.data.columns.tolist())
        print("总行数: ",len(self.data))
        print(self.data.head())
        print("===第4行完整原始数据===")
        print(self.data.iloc[4])
        # 建立分词索引，提升搜索匹配效率
        self.index = {}
        for real_idx, (_, row) in enumerate(self.data.iterrows( )):
           name_str = str(row["name"])
           tag_str = str(row["tags"])
           print(f"第{real_idx}行原始tag_str={repr(tag_str)}")
           tag_list = [ ]
           try:
               if tag_str.startswith('[') and tag_str.endswith(']'):
                   tag_list = ast.literal_eval(tag_str)
               else:
                      tag_list = tag_str.split(',')
           except Exception as e:
               print(f"解析tags失败:{e}")
               tag_list = [ ]
           print(f"第{real_idx}行: tag_list={tag_list}")
           tag_str_join = " ".join(tag_list)
           words = jieba.lcut(name_str + " " + tag_str_join)
           for word in words:
                word = word.strip()
                if not word or word.replace(".","").isdigit():
                    continue
                if word not in self.index:
                    self.index[word] = []
                self.index[word].append(real_idx)
        print("索引的词: ",list(self.index.keys())[:10])
        print("索引总词数: ",len(self.index))
    
    def search_food(self, user_query):
        """根据用户需求检索匹配的美食结果"""
        query_words = jieba.lcut(user_query)
        print(f"查询分词结果：{query_words}") #新增打印
        match_ids = set()
        for word in query_words:
            print(f"正在匹配词：{word}，是否在索引：{word in self.index}") #新增打印
            if word in self.index:
             match_ids.update(self.index[word])
        print(f"命中id集合:{match_ids}")
        result = [self.data.iloc[i].to_dict() for i in sorted(match_ids)]
        return result

# ---------------------- 3. 探店内容生成AI模块 ----------------------
class FoodReviewGenerator:
    def __init__(self):
        # 轻量级中文生成模型，本地运行无需联网
        self.generator = pipeline("text-generation", model="uer/gpt2-chinese-cluecorpussmall")