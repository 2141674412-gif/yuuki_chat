"""
数据迁移脚本
用于将旧数据迁移到新的目录结构
"""

import os
import shutil
import json
from datetime import datetime

def migrate_data():
    """执行数据迁移"""
    old_data_dir = os.path.join(os.getcwd(), "plugins", "yuuki_chat")
    new_data_dir = os.path.join(os.getcwd(), "yuuki_data")
    
    # 需要迁移的文件列表
    files_to_migrate = [
        "mai_binds.json",
        "user_points.json",
        "user_data.json",
        "chat_history.json",
        "reminders.json",
        "blacklist.json",
        "admin_list.json",
        "birthday.json",
        "accounting.json",
        "config.json",
        ".version",
    ]
    
    # 需要迁移的目录
    dirs_to_migrate = [
        "update",
        "backup",
        "cache",
        "wordcloud",
    ]
    
    # 创建新数据目录
    os.makedirs(new_data_dir, exist_ok=True)
    
    migrated_count = 0
    skipped_count = 0
    
    # 迁移文件
    for filename in files_to_migrate:
        old_path = os.path.join(old_data_dir, filename)
        new_path = os.path.join(new_data_dir, filename)
        
        if os.path.exists(old_path):
            if not os.path.exists(new_path):
                shutil.copy2(old_path, new_path)
                migrated_count += 1
                print(f"迁移文件: {filename}")
            else:
                skipped_count += 1
                print(f"跳过已存在: {filename}")
    
    # 迁移目录
    for dirname in dirs_to_migrate:
        old_path = os.path.join(old_data_dir, dirname)
        new_path = os.path.join(new_data_dir, dirname)
        
        if os.path.exists(old_path):
            if not os.path.exists(new_path):
                shutil.copytree(old_path, new_path)
                migrated_count += 1
                print(f"迁移目录: {dirname}")
            else:
                skipped_count += 1
                print(f"跳过已存在: {dirname}")
    
    print(f"\n迁移完成！")
    print(f"迁移: {migrated_count} 个项目")
    print(f"跳过: {skipped_count} 个项目")
    
    # 创建迁移标记文件
    migrate_info = {
        "migrated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "migrated_count": migrated_count,
        "skipped_count": skipped_count,
        "old_dir": old_data_dir,
        "new_dir": new_data_dir,
    }
    
    with open(os.path.join(new_data_dir, "migrate_info.json"), "w", encoding="utf-8") as f:
        json.dump(migrate_info, f, ensure_ascii=False, indent=2)
    
    return migrated_count > 0


if __name__ == "__main__":
    try:
        migrate_data()
    except Exception as e:
        print(f"迁移失败: {e}")
        import traceback
        traceback.print_exc()
