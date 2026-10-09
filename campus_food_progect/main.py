from campus_food import CampusFoodCrawler, FoodKnowledgeBase, FoodReviewGenerator

if __name__ == "__main__":
    # 跳过爬虫，直接加载本地测试知识库
    kb = FoodKnowledgeBase()
    result = kb.search_food("火锅")
    print("检索结果: ", result)

    # AI生成探店文案
    #gen = FoodReviewGenerator()
    #output = gen.generate("这家火锅味道很不错")
    #print("AI探店文案: ", output)

    #=====测试调试代码=====
    print("===索引字典===")
    print(kb.index)
    print("===搜索夜宵===")
    print(kb.search_food("夜宵"))
    print("===搜索炸鸡===")
    print(kb.search_food("炸鸡"))