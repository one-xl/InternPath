import streamlit as st
from collections import defaultdict
from service import CareerPathAIService

st.set_page_config(
    page_title="CareerPath AI - 职业规划助手",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 CareerPath AI - 职业规划助手")
st.markdown("---")

@st.cache_resource
def get_service():
    return CareerPathAIService()

service = get_service()

if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None
if 'courses_result' not in st.session_state:
    st.session_state.courses_result = None
if 'search_courses' not in st.session_state:
    st.session_state.search_courses = False
if 'searching' not in st.session_state:
    st.session_state.searching = False
if 'jd_text' not in st.session_state:
    st.session_state.jd_text = ""

st.subheader("📝 输入岗位 JD")
jd_text = st.text_area("请粘贴岗位招聘要求（JD）：", height=200)

col1, col2 = st.columns([1, 4])
with col1:
    analyze_button = st.button("🔍 开始分析", type="primary")

if analyze_button and jd_text:
    with st.spinner("正在分析 JD..."):
        try:
            # 只提取技能，不搜索课程
            analysis = service.extract_skills(jd_text)
            st.session_state.analysis_result = analysis
            st.session_state.courses_result = None
            st.session_state.search_courses = False
            st.session_state.jd_text = jd_text
            st.success("分析完成！")
        except Exception as e:
            st.error(f"分析失败：{str(e)}")

if st.session_state.analysis_result:
    analysis = st.session_state.analysis_result
    
    st.markdown("---")
    st.subheader("📊 分析结果")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric("难度评估", analysis.difficulty)
    
    with col2:
        st.info(f"**岗位简述：** {analysis.job_summary}")
    
    st.subheader("🎯 提取的技能")
    skill_cols = st.columns(4)
    for idx, skill in enumerate(analysis.skills):
        with skill_cols[idx % 4]:
            st.success(f"💡 {skill}")
    
    # 询问是否搜索课程
    if not st.session_state.search_courses:
        st.markdown("---")
        st.subheader("🔍 课程搜索")
        if st.button("开始搜索相关课程", type="primary"):
            st.session_state.search_courses = True
            st.session_state.searching = True
    
    # 搜索课程
    if st.session_state.searching:
        with st.spinner("正在搜索课程..."):
            try:
                # 单独搜索课程
                courses = service.search_courses(analysis.skills)
                st.session_state.courses_result = courses
                st.session_state.searching = False
                
                # 保存到数据库
                jd_record_id = service.db.save_jd_record(st.session_state.jd_text, analysis)
                service.db.save_courses(jd_record_id, courses)
                
                st.success("课程搜索完成！")
            except Exception as e:
                st.error(f"课程搜索失败：{str(e)}")
                st.session_state.searching = False
    
    # 显示课程结果
    if st.session_state.courses_result:
        courses = st.session_state.courses_result
        
        st.markdown("---")
        st.subheader("📚 推荐课程")
        
        skill_courses = defaultdict(list)
        for course in courses:
            skill_courses[course.skill].append(course)
        
        for skill, skill_course_list in skill_courses.items():
            st.markdown(f"### 🔹 {skill}")
            course_cols = st.columns(3)
            for idx, course in enumerate(skill_course_list[:3]):
                with course_cols[idx]:
                    with st.container(border=True):
                        st.markdown(f"**[{course.title}]({course.url})**")
                        st.caption(f"UP主: {course.uploader} | 日期: {course.publish_date}")
                        st.write(f"播放: {course.view_count:,} | 收藏: {course.favorite_count:,} | 点赞: {course.like_count:,}")
                        st.progress(course.rank_score / 100, text=f"综合评分: {course.rank_score:.1f}")
    
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        sync_button = st.button("💻 一键同步至刷题软件", type="primary")
    
    if sync_button:
        with st.spinner("正在同步..."):
            success = service.sync_to_practice_app(analysis.skills)
            if success:
                st.success("同步成功！刷题软件已启动。")
            else:
                st.warning("技能包已导出，请手动启动刷题软件导入。")
                st.info(f"技能包路径: {service.practice_invoker.skillpkg_path}")

st.markdown("---")
st.caption("CareerPath AI © 2026 | 让职业规划更简单")
