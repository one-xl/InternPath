import json
import subprocess
import os
from typing import List
from config import Config
from models import SkillPackage

class PracticeAppInvoker:
    def __init__(self):
        self.app_path = Config.PRACTICE_APP_PATH
        self.skillpkg_path = Config.TEMP_SKILLPKG_PATH
    
    def export_skill_package(self, skills: List[str]) -> str:
        skill_package = SkillPackage(skills=skills)
        
        with open(self.skillpkg_path, 'w', encoding='utf-8') as f:
            json.dump(skill_package.model_dump(), f, ensure_ascii=False, indent=2)
        
        return self.skillpkg_path
    
    def invoke_practice_app(self, skills: List[str]) -> bool:
        if not skills:
            print("没有技能需要同步")
            return False
        
        try:
            skillpkg_file = self.export_skill_package(skills)
            
            if not os.path.exists(self.app_path):
                print(f"警告：刷题软件路径不存在: {self.app_path}")
                print(f"技能包已导出到: {skillpkg_file}")
                return False
            
            args = [
                self.app_path,
                '--import',
                skillpkg_file
            ]
            
            subprocess.Popen(args)
            print(f"已成功启动刷题软件，导入技能包: {skillpkg_file}")
            return True
            
        except Exception as e:
            print(f"调用刷题软件失败: {str(e)}")
            return False
