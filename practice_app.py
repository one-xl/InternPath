import base64
import json
import os
import subprocess
from typing import List, Literal, Optional, Union

from config import Config
from models import ExamOptionsForPractice, JobContextForPractice, SkillPackage

PracticeMode = Literal["direct", "ai_recommend"]

# 与 C# 刷题软件约定的命令行：见仓库说明或下方 build_practice_launch_args
MODE_CLI = {"direct": "direct", "ai_recommend": "ai-recommend"}


def _coalesce_exam_options(
    exam_options: Optional[Union[ExamOptionsForPractice, dict]],
) -> Optional[ExamOptionsForPractice]:
    if exam_options is None:
        return None
    if isinstance(exam_options, ExamOptionsForPractice):
        return exam_options
    return ExamOptionsForPractice.model_validate(exam_options)


class PracticeAppInvoker:
    def __init__(self):
        self.app_path = Config.PRACTICE_APP_PATH
        self.skillpkg_path = Config.TEMP_SKILLPKG_PATH
        self.protocol_scheme = os.getenv("PRACTICE_PROTOCOL_SCHEME", "aismartdrill").strip() or "aismartdrill"

    def build_skill_package(
        self,
        skills: List[str],
        practice_mode: PracticeMode,
        *,
        job_summary: str = "",
        difficulty: str = "",
        exam_options: Optional[Union[ExamOptionsForPractice, dict]] = None,
    ) -> SkillPackage:
        return SkillPackage(
            skills=skills,
            practice_mode=practice_mode,
            job_context=JobContextForPractice(
                difficulty=difficulty or "",
                job_summary=job_summary or "",
            ),
            exam_options=_coalesce_exam_options(exam_options),
        )

    @staticmethod
    def dumps_skill_package(pkg: SkillPackage) -> str:
        return json.dumps(
            pkg.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def build_skill_package_json(
        self,
        skills: List[str],
        practice_mode: PracticeMode,
        *,
        job_summary: str = "",
        difficulty: str = "",
        exam_options: Optional[Union[ExamOptionsForPractice, dict]] = None,
    ) -> str:
        pkg = self.build_skill_package(
            skills,
            practice_mode,
            job_summary=job_summary,
            difficulty=difficulty,
            exam_options=exam_options,
        )
        return self.dumps_skill_package(pkg)

    def export_skill_package(
        self,
        skills: List[str],
        practice_mode: PracticeMode,
        *,
        job_summary: str = "",
        difficulty: str = "",
        exam_options: Optional[Union[ExamOptionsForPractice, dict]] = None,
    ) -> str:
        pkg_json = self.build_skill_package_json(
            skills,
            practice_mode,
            job_summary=job_summary,
            difficulty=difficulty,
            exam_options=exam_options,
        )
        with open(self.skillpkg_path, "w", encoding="utf-8") as f:
            parsed = json.loads(pkg_json)
            json.dump(parsed, f, ensure_ascii=False, indent=2)
        return self.skillpkg_path

    def build_protocol_url(
        self,
        skills: List[str],
        practice_mode: PracticeMode,
        *,
        job_summary: str = "",
        difficulty: str = "",
        exam_options: Optional[Union[ExamOptionsForPractice, dict]] = None,
        auto_proceed: bool = False,
    ) -> str:
        payload = self.build_skill_package_json(
            skills,
            practice_mode,
            job_summary=job_summary,
            difficulty=difficulty,
            exam_options=exam_options,
        )
        encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
        if auto_proceed:
            return f"{self.protocol_scheme}://launch?payload={encoded}&auto=1"
        return f"{self.protocol_scheme}://launch?payload={encoded}"

    @staticmethod
    def build_launch_args(
        exe_path: str,
        skillpkg_file: str,
        practice_mode: PracticeMode,
        *,
        auto_proceed: bool = False,
    ) -> List[str]:
        """
        供 C# 端解析：--import <json> --mode direct|ai-recommend [--auto]。

        默认不传 --auto：用户在网页点击「启动刷题软件」后，仍可在 WPF 内二次确认
        （是否开考 / 是否发起 AI 推荐），避免与 Streamlit 提示「请在软件内确认」不一致。

        若 auto_proceed=True，则附加 --auto，与浏览器唤醒、无人值守场景配合，跳过 WPF 确认框。
        """
        args: List[str] = [
            exe_path,
            "--import",
            skillpkg_file,
            "--mode",
            MODE_CLI[practice_mode],
        ]
        if auto_proceed:
            args.append("--auto")
        return args

    def invoke_practice_app(
        self,
        skills: List[str],
        practice_mode: PracticeMode,
        *,
        job_summary: str = "",
        difficulty: str = "",
        exam_options: Optional[Union[ExamOptionsForPractice, dict]] = None,
        auto_proceed: bool = False,
    ) -> bool:
        if not skills:
            print("没有技能需要同步")
            return False

        try:
            skillpkg_file = self.export_skill_package(
                skills,
                practice_mode,
                job_summary=job_summary,
                difficulty=difficulty,
                exam_options=exam_options,
            )

            if not os.path.exists(self.app_path):
                print(f"警告：刷题软件路径不存在: {self.app_path}")
                print(f"技能包已导出到: {skillpkg_file}")
                return False

            args = self.build_launch_args(
                self.app_path,
                skillpkg_file,
                practice_mode,
                auto_proceed=auto_proceed,
            )
            app_dir = os.path.dirname(os.path.abspath(self.app_path))
            subprocess.Popen(args, cwd=app_dir or None)
            print(f"已启动刷题软件，模式={practice_mode}，技能包: {skillpkg_file}")
            return True

        except Exception as e:
            print(f"调用刷题软件失败: {str(e)}")
            return False
