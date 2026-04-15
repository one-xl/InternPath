import asyncio
from crawler_api import BilibiliAPICrawler, BilibiliAPICrawlerSync


async def test_async_crawler():
    print("测试异步爬虫...")
    try:
        async with BilibiliAPICrawler() as crawler:
            courses = await crawler.search_skill("Python", max_results=5)
            
            print(f"\n找到 {len(courses)} 个课程：")
            for i, course in enumerate(courses, 1):
                print(f"\n{i}. {course.title}")
                print(f"   播放量: {course.view_count}")
                print(f"   点赞: {course.like_count}")
                print(f"   投币: {course.coin_count}")
                print(f"   收藏: {course.favorite_count}")
                print(f"   弹幕: {course.danmaku_count}")
                print(f"   UP主: {course.uploader}")
                print(f"   日期: {course.publish_date}")
                print(f"   时长: {course.duration}")
                print(f"   URL: {course.url}")
                
    except Exception as e:
        print(f"异步爬虫测试失败: {e}")


def test_sync_crawler():
    print("\n" + "="*50)
    print("测试同步爬虫...")
    try:
        crawler = BilibiliAPICrawlerSync()
        courses = crawler.search_skill("Java", max_results=5)
        
        print(f"\n找到 {len(courses)} 个课程：")
        for i, course in enumerate(courses, 1):
            print(f"\n{i}. {course.title}")
            print(f"   播放量: {course.view_count}")
            print(f"   点赞: {course.like_count}")
            print(f"   投币: {course.coin_count}")
            print(f"   收藏: {course.favorite_count}")
            print(f"   UP主: {course.uploader}")
            print(f"   日期: {course.publish_date}")
            print(f"   URL: {course.url}")
            
    except Exception as e:
        print(f"同步爬虫测试失败: {e}")


if __name__ == "__main__":
    print("开始测试B站API爬虫...")
    print("="*50)
    
    test_sync_crawler()
    
    print("\n" + "="*50)
    print("测试完成！")
