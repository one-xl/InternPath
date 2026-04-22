import base64
import binascii
import hashlib
import hmac
import os
import time
from collections import defaultdict
from typing import Optional

import streamlit as st

from models import ExamOptionsForPractice, JDRecord
from service import CareerPathAIService


APP_PASSWORD = os.getenv("APP_PASSWORD", "")
APP_PASSWORD_HASH = os.getenv("APP_PASSWORD_HASH", "").strip()
LOGIN_MAX_ATTEMPTS = 5
LOGIN_BASE_LOCK_SECONDS = 30
LOGIN_MAX_LOCK_SECONDS = 900
MAX_RECORD_NAME_LENGTH = 60
IS_WINDOWS_RUNTIME = os.name == "nt"
DRAFT_RECORD_OPTION = "__draft_record_option__"
LAUNCH_ACTION_STYLE = """
<style>
  .launch-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.75rem;
    margin: 0.5rem 0 1rem 0;
  }
  .launch-action,
  .launch-action:link,
  .launch-action:visited,
  .launch-action:hover,
  .launch-action:active,
  .launch-action:focus,
  a[href^="aismartdrill://"],
  a[href^="aismartdrill://"]:link,
  a[href^="aismartdrill://"]:visited,
  a[href^="aismartdrill://"]:hover,
  a[href^="aismartdrill://"]:active,
  a[href^="aismartdrill://"]:focus {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 2.9rem;
    padding: 0 1rem;
    border-radius: 0.85rem;
    border: 1px solid transparent;
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    text-decoration: none !important;
    font-weight: 800;
    font-size: 1rem;
    letter-spacing: 0.01em;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
  }
  .launch-action span,
  a[href^="aismartdrill://"] span {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
  }
  .launch-action--direct {
    background: #1d4ed8;
    border-color: #1e40af;
  }
  .launch-action--ai {
    background: #0f766e;
    border-color: #115e59;
  }
</style>
"""

st.set_page_config(
    page_title="CareerPath AI - 职业规划助手",
    page_icon="🎯",
    layout="wide",
)


def ensure_state():
    defaults = {
        "authenticated": False,
        "login_failed_attempts": 0,
        "login_locked_until": 0.0,
        "analysis_result": None,
        "courses_result": None,
        "search_courses": False,
        "searching": False,
        "selected_record_id": None,
        "draft_analysis": False,
        "jd_record_id": None,
        "jd_text": "",
        "jd_text_input": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def parse_password_hash(value: str) -> Optional[tuple[int, bytes, bytes]]:
    try:
        scheme, iterations, salt_b64, digest_b64 = value.split("$", 3)
    except ValueError:
        return None

    if scheme != "pbkdf2_sha256":
        return None

    try:
        return (
            int(iterations),
            base64.b64decode(salt_b64.encode("ascii")),
            base64.b64decode(digest_b64.encode("ascii")),
        )
    except (ValueError, binascii.Error):
        return None


def verify_password(password: str) -> bool:
    if APP_PASSWORD_HASH:
        parsed = parse_password_hash(APP_PASSWORD_HASH)
        if parsed is None:
            return False

        iterations, salt, expected_digest = parsed
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(digest, expected_digest)

    if not APP_PASSWORD:
        return False

    return hmac.compare_digest(password, APP_PASSWORD)


def reset_login_throttle():
    st.session_state.login_failed_attempts = 0
    st.session_state.login_locked_until = 0.0


def register_failed_login():
    attempts = st.session_state.login_failed_attempts + 1
    st.session_state.login_failed_attempts = attempts
    if attempts < LOGIN_MAX_ATTEMPTS:
        return

    exponent = attempts - LOGIN_MAX_ATTEMPTS
    lock_seconds = min(LOGIN_MAX_LOCK_SECONDS, LOGIN_BASE_LOCK_SECONDS * (2**exponent))
    st.session_state.login_locked_until = time.time() + lock_seconds


def render_login_gate() -> bool:
    if st.session_state.authenticated:
        return True

    st.title("🔐 InternPath 访问验证")
    st.caption("请输入访问密码后继续。")

    remaining_lock = max(0, int(st.session_state.login_locked_until - time.time()))
    if remaining_lock > 0:
        st.warning(f"尝试次数过多，请在 {remaining_lock} 秒后再试。")

    with st.form("login_form", clear_on_submit=False):
        password = st.text_input("访问密码", type="password")
        submitted = st.form_submit_button(
            "进入系统",
            type="primary",
            disabled=remaining_lock > 0,
        )

    if submitted and remaining_lock <= 0:
        if verify_password(password):
            st.session_state.authenticated = True
            reset_login_throttle()
            st.rerun()

        register_failed_login()
        st.error("访问密码错误。")

    return st.session_state.authenticated


def build_record_label(record: JDRecord) -> str:
    display_name = (record.display_name or "").strip()
    if display_name:
        return display_name

    snippet = (record.jd_text or "").replace("\n", " ").strip()
    if snippet:
        return snippet[:24] + "..." if len(snippet) > 24 else snippet
    return "未命名记录"


def load_record_into_state(service: CareerPathAIService, record_id: int):
    record = service.get_jd_record(record_id)
    if record is None:
        return

    courses = service.db.get_courses_by_jd_id(record_id)
    st.session_state.analysis_result = record.analysis
    st.session_state.courses_result = courses if courses else None
    st.session_state.search_courses = bool(courses)
    st.session_state.searching = False
    st.session_state.jd_record_id = record_id
    st.session_state.jd_text = record.jd_text
    st.session_state.jd_text_input = record.jd_text
    st.session_state.selected_record_id = record_id
    st.session_state.draft_analysis = False


def reset_current_record(*, draft_analysis: bool = False):
    st.session_state.analysis_result = None
    st.session_state.courses_result = None
    st.session_state.search_courses = False
    st.session_state.searching = False
    st.session_state.jd_record_id = None
    st.session_state.jd_text = ""
    st.session_state.jd_text_input = ""
    st.session_state.draft_analysis = draft_analysis


def start_new_analysis():
    reset_current_record(draft_analysis=True)
    st.session_state.selected_record_id = None


def save_current_analysis(service: CareerPathAIService):
    analysis = st.session_state.get("analysis_result")
    analyzed_jd = (st.session_state.get("jd_text") or "").strip()
    current_input = (st.session_state.get("jd_text_input") or "").strip()

    if analysis is None or not analyzed_jd:
        st.error("请先完成 JD 分析后再保存。")
        return

    if current_input != analyzed_jd:
        st.error("当前 JD 已修改，请重新点击“开始分析”后再保存。")
        return

    if st.session_state.get("jd_record_id") is not None:
        st.info("当前分析已在历史记录中。")
        return

    jd_id = service.db.save_jd_record(analyzed_jd, analysis)
    courses = st.session_state.get("courses_result") or []
    if courses:
        service.db.save_courses(jd_id, courses, replace=True)

    st.session_state.jd_record_id = jd_id
    st.session_state.selected_record_id = jd_id
    st.session_state.draft_analysis = False
    st.success("已保存到历史记录。")


def show_safe_error(message: str, exc: Exception):
    print(f"{message}: {exc}")
    st.error(message)


@st.cache_resource
def get_service():
    return CareerPathAIService()


def render_history_sidebar(service: CareerPathAIService):
    with st.sidebar:
        st.subheader("分析历史")
        st.caption("使用下拉框选择历史记录。")

        if st.button("添加分析", use_container_width=True, type="primary"):
            start_new_analysis()
            st.rerun()

        history = service.get_history(80)
        if not history:
            if st.session_state.get("draft_analysis"):
                st.caption("当前正在编辑新的分析。")
            else:
                st.info("暂无历史记录。")
            return

        record_by_id = {record.id: record for record in history if record.id is not None}
        options = [record.id for record in history if record.id is not None]
        if not options:
            return

        current_id = st.session_state.get("selected_record_id")
        history_options = options
        if st.session_state.get("draft_analysis"):
            history_options = [DRAFT_RECORD_OPTION, *options]
            current_id = DRAFT_RECORD_OPTION
        elif current_id not in record_by_id:
            current_id = options[0]

        record_id = st.selectbox(
            "选择记录",
            history_options,
            index=history_options.index(current_id),
            format_func=lambda rid: "新增分析（未保存）" if rid == DRAFT_RECORD_OPTION else build_record_label(record_by_id[rid]),
            key="sidebar_history_select",
        )

        if record_id == DRAFT_RECORD_OPTION:
            st.caption("当前正在编辑新的分析，完成后可手动保存到历史记录。")
            return

        current_record = record_by_id[record_id]
        if st.session_state.get("selected_record_id") != record_id:
            load_record_into_state(service, record_id)
            st.rerun()

        st.caption(f"创建时间：{current_record.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

        with st.expander("记录管理", expanded=False):
            default_name = (current_record.display_name or "").strip()
            new_name = st.text_input(
                "记录名称",
                value=default_name,
                max_chars=MAX_RECORD_NAME_LENGTH,
                key=f"record_name_{record_id}",
                help="留空会回退到 JD 文本摘要。",
            )

            if st.button("保存名称", use_container_width=True, key=f"rename_{record_id}"):
                trimmed = new_name.strip()
                if len(trimmed) > MAX_RECORD_NAME_LENGTH:
                    st.error(f"名称不能超过 {MAX_RECORD_NAME_LENGTH} 个字符。")
                else:
                    service.rename_jd_record(record_id, trimmed or None)
                    st.success("记录名称已更新。")
                    st.rerun()

            confirm_delete = st.checkbox(
                "确认删除该记录及其课程数据",
                key=f"confirm_delete_{record_id}",
            )
            if st.button("删除记录", use_container_width=True, key=f"delete_{record_id}"):
                if not confirm_delete:
                    st.error("请先勾选确认删除。")
                else:
                    service.delete_jd_record(record_id)
                    if st.session_state.jd_record_id == record_id:
                        reset_current_record()
                        st.session_state.selected_record_id = None
                    st.success("记录已删除。")
                    st.rerun()


def render_analysis_input(service: CareerPathAIService):
    st.subheader("输入岗位 JD")
    jd_text = st.text_area(
        "请粘贴岗位职责或招聘要求：",
        height=220,
        key="jd_text_input",
    )

    col1, col2, _ = st.columns([1, 1, 3])
    with col1:
        analyze_button = st.button("开始分析", type="primary")
    with col2:
        save_button = st.button(
            "保存到历史",
            use_container_width=True,
            disabled=st.session_state.get("analysis_result") is None or st.session_state.get("jd_record_id") is not None,
        )

    if analyze_button:
        jd_text = jd_text.strip()
        if not jd_text:
            st.error("请先输入 JD 内容。")
            return
        with st.spinner("正在分析 JD..."):
            try:
                analysis = service.extract_skills(jd_text)
                st.session_state.analysis_result = analysis
                st.session_state.courses_result = None
                st.session_state.search_courses = False
                st.session_state.searching = False
                st.session_state.jd_text = jd_text
                st.session_state.jd_text_input = jd_text
                st.session_state.jd_record_id = None
                st.session_state.selected_record_id = None
                st.session_state.draft_analysis = True
                st.success("分析完成，可选择保存到历史记录。")
            except Exception as exc:
                show_safe_error("分析失败，请稍后重试。", exc)

    if save_button:
        save_current_analysis(service)


def render_courses(service: CareerPathAIService, analysis):
    if not st.session_state.search_courses:
        st.markdown("---")
        st.subheader("课程搜索")
        if st.button("开始搜索相关课程", type="primary"):
            st.session_state.search_courses = True
            st.session_state.searching = True

    if st.session_state.searching:
        with st.spinner("正在搜索课程..."):
            try:
                courses = service.search_courses(analysis.skills)
                st.session_state.courses_result = courses
                st.session_state.searching = False

                jd_id = st.session_state.jd_record_id
                if jd_id is None:
                    st.success("课程搜索完成，可预览结果并在保存分析后写入历史记录。")
                else:
                    service.db.save_courses(jd_id, courses, replace=True)
                    st.success("课程搜索完成，结果已写入当前历史记录。")
            except Exception as exc:
                st.session_state.searching = False
                show_safe_error("课程搜索失败，请稍后重试。", exc)

    if not st.session_state.courses_result:
        return

    st.markdown("---")
    st.subheader("推荐课程")

    skill_courses = defaultdict(list)
    for course in st.session_state.courses_result:
        skill_courses[course.skill].append(course)

    for skill, course_list in skill_courses.items():
        st.markdown(f"### {skill}")
        cols = st.columns(3)
        for idx, course in enumerate(course_list[:3]):
            with cols[idx]:
                with st.container(border=True):
                    st.markdown(f"**[{course.title}]({course.url})**")
                    st.caption(f"UP 主：{course.uploader} | 日期：{course.publish_date}")
                    st.write(
                        f"播放：{course.view_count:,} | 收藏：{course.favorite_count:,} | 点赞：{course.like_count:,}"
                    )
                    st.progress(course.rank_score / 100, text=f"综合评分：{course.rank_score:.1f}")


def _sync_practice_exam_state(analysis):
    """分析结果变化时重置刷题选项默认值（领域、难度、题量）。"""
    sig = (
        st.session_state.get("jd_record_id"),
        tuple(analysis.skills),
        getattr(analysis, "difficulty", "") or "",
        getattr(analysis, "job_summary", "") or "",
    )
    if st.session_state.get("_practice_exam_state_sig") == sig:
        return

    st.session_state["_practice_exam_state_sig"] = sig
    st.session_state["include_exam_options"] = False
    st.session_state["practice_domain_hint"] = (analysis.skills[0] if analysis.skills else "")
    d = (analysis.difficulty or "").strip()
    st.session_state["practice_exam_difficulty"] = (
        d if d in ("简单", "中等", "困难") else "（不限制）"
    )
    st.session_state["practice_question_count"] = 10


def _build_exam_options_from_session() -> Optional[ExamOptionsForPractice]:
    if not st.session_state.get("include_exam_options"):
        return None

    domain = (st.session_state.get("practice_domain_hint") or "").strip()
    diff_choice = st.session_state.get("practice_exam_difficulty") or "（不限制）"
    exam_difficulty = None if diff_choice == "（不限制）" else diff_choice
    qc = int(st.session_state.get("practice_question_count") or 10)

    if not domain and exam_difficulty is None:
        return ExamOptionsForPractice(question_count=qc)

    return ExamOptionsForPractice(
        domain_hint=domain or None,
        difficulty=exam_difficulty,
        question_count=qc,
    )


def render_practice_sync(service: CareerPathAIService, analysis):
    st.markdown("---")
    st.subheader("刷题软件联动（AiSmartDrill）")

    _sync_practice_exam_state(analysis)

    with st.expander("刷题选项（可选，写入技能包 exam_options）", expanded=False):
        st.checkbox(
            "在技能包中包含 exam_options",
            key="include_exam_options",
            help="勾选后会把领域提示、组卷难度与题量写入 JSON；不勾选则与旧版行为一致。",
        )
        st.caption(
            "domain_hint 应与 AiSmartDrill「领域」下拉的枚举文案一致或相近，否则客户端可能无法匹配。"
        )
        st.text_input(
            "领域提示（domain_hint）",
            key="practice_domain_hint",
            help="默认可用分析结果中的首个技能；可按需改成与客户端领域列表一致的名称。",
        )
        st.selectbox(
            "组卷难度（exam_options.difficulty）",
            ["（不限制）", "简单", "中等", "困难"],
            key="practice_exam_difficulty",
            help="默认倾向 JD 分析难度；「不限制」表示不在组卷对话框中预设难度。",
        )
        st.number_input(
            "题量（question_count）",
            min_value=1,
            max_value=50,
            step=1,
            key="practice_question_count",
            help="本次组卷题目数量（1～50）。",
        )

    exam_options = _build_exam_options_from_session()

    if not IS_WINDOWS_RUNTIME:
        st.caption("服务器版网页只能发起本地唤起，前提是你的 Windows 程序已经注册自定义协议。")

        direct_launch_url = service.build_practice_protocol_url(
            analysis.skills,
            practice_mode="direct",
            job_summary=analysis.job_summary,
            difficulty=analysis.difficulty,
            exam_options=exam_options,
            auto_proceed=True,
        )
        ai_launch_url = service.build_practice_protocol_url(
            analysis.skills,
            practice_mode="ai_recommend",
            job_summary=analysis.job_summary,
            difficulty=analysis.difficulty,
            exam_options=exam_options,
            auto_proceed=True,
        )

        st.markdown(LAUNCH_ACTION_STYLE, unsafe_allow_html=True)
        st.markdown(
            f"""
            <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0.75rem;margin:0.5rem 0 1rem 0;">
              <a href="{direct_launch_url}" target="_self" style="display:flex;align-items:center;justify-content:center;height:2.9rem;padding:0 1rem;border-radius:0.85rem;background:#1d4ed8;border:1px solid #1e40af;color:#ffffff !important;-webkit-text-fill-color:#ffffff !important;text-decoration:none;font-weight:700;font-size:1rem;letter-spacing:0.01em;">
                打开本地刷题软件
              </a>
              <a href="{ai_launch_url}" target="_self" style="display:flex;align-items:center;justify-content:center;height:2.9rem;padding:0 1rem;border-radius:0.85rem;background:#0f766e;border:1px solid #115e59;color:#ffffff !important;-webkit-text-fill-color:#ffffff !important;text-decoration:none;font-weight:700;font-size:1rem;letter-spacing:0.01em;">
                打开本地 AI 推荐
              </a>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.info("点击后会直接启动本地刷题流程，不再弹二次确认框。若浏览器询问是否打开 AiSmartDrill，需要手动点允许。")
        return

    st.caption("仅在本机 Windows 环境下可 subprocess 启动 exe；路径由 PRACTICE_APP_PATH 配置。")

    skip_desktop_confirm = st.checkbox(
        "跳过桌面端二次确认（--auto）",
        value=False,
        key="skip_desktop_confirm",
    )

    col1, col2 = st.columns(2)
    with col1:
        launch_direct = st.button(
            "直接刷题",
            type="primary",
            use_container_width=True,
            key="btn_launch_direct",
        )
    with col2:
        launch_ai = st.button(
            "AI 推荐题目",
            type="primary",
            use_container_width=True,
            key="btn_launch_ai",
        )

    if not (launch_direct or launch_ai):
        return

    chosen_mode = "direct" if launch_direct else "ai_recommend"
    with st.spinner("正在导出技能包并连接刷题软件..."):
        success = service.sync_to_practice_app(
            analysis.skills,
            practice_mode=chosen_mode,
            job_summary=analysis.job_summary,
            difficulty=analysis.difficulty,
            exam_options=exam_options,
            auto_proceed=skip_desktop_confirm,
        )

    if success:
        st.success("已连接刷题软件。")
    else:
        st.warning("未找到可执行文件，已保留导出的技能包。")
        st.info(f"技能包路径：`{service.practice_invoker.skillpkg_path}`")


def render_analysis_result(service: CareerPathAIService):
    analysis = st.session_state.analysis_result
    if analysis is None:
        return

    st.markdown("---")
    st.subheader("分析结果")

    if st.session_state.get("jd_record_id") is None:
        st.info("当前分析尚未保存到历史记录。")

    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric("难度评估", analysis.difficulty)
    with col2:
        st.info(f"**岗位概述：** {analysis.job_summary}")

    st.subheader("提取的技能")
    skill_cols = st.columns(4)
    for idx, skill in enumerate(analysis.skills):
        with skill_cols[idx % 4]:
            st.success(f"🔹 {skill}")

    render_courses(service, analysis)
    render_practice_sync(service, analysis)


ensure_state()
if not render_login_gate():
    st.stop()

service = get_service()

st.title("🎯 CareerPath AI - 职业规划助手")
st.markdown("---")
render_history_sidebar(service)
render_analysis_input(service)
render_analysis_result(service)

st.markdown("---")
st.caption("CareerPath AI © 2026")
