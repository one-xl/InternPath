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

st.subheader("📝 输入岗位 JD")
jd_text = st.text_area("请粘贴岗位招聘要求（JD）：", height=200)

col1, col2 = st.columns([1, 4])
with col1:
    analyze_button = st.button("🔍 开始分析", type="primary")

if analyze_button and jd_text:
    with st.spinner("正在分析 JD 并搜索课程..."):
        try:
            analysis, courses = service.analyze_jd(jd_text)
            st.session_state.analysis_result = analysis
            st.session_state.courses_result = courses
            st.success("分析完成！")
        except Exception as e:
            st.error(f"分析失败：{str(e)}")

if st.session_state.analysis_result:
    analysis = st.session_state.analysis_result
    courses = st.session_state.courses_result
    
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
