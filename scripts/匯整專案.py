#!/usr/bin/env python3
"""
專案整合工具 - 把資料夾結構和程式碼整合成單一檔案
用途：上傳到 Claude 專案作為 context
"""

import os
from pathlib import Path
from datetime import datetime

# ===== 設定 =====
IGNORE_DIRS = {'.git', '__pycache__', '.venv', 'venv', 'node_modules', '.idea', '.vscode', 'dist', 'build', '__MACOSX'}
IGNORE_FILES = {'.DS_Store', 'Thumbs.db', '.gitignore', '*.pyc', '*.pyo'}
CODE_EXTENSIONS = {'.py', '.js', '.ts', '.html', '.css', '.json', '.yaml', '.yml', '.md', '.txt', '.sql', '.sh', '.env.example'}
MAX_FILE_SIZE = 100 * 1024  # 100KB，超過的檔案只顯示路徑不顯示內容


def should_ignore(path: Path) -> bool:
    """判斷是否要忽略此路徑"""
    if path.name in IGNORE_DIRS or path.name in IGNORE_FILES:
        return True
    if path.name.startswith('.') and path.name not in {'.env.example'}:
        return True
    return False


def generate_tree(root: Path, prefix: str = "") -> list[str]:
    """產生目錄樹狀圖"""
    lines = []
    items = sorted(root.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    items = [x for x in items if not should_ignore(x)]
    
    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        
        if item.is_dir():
            lines.append(f"{prefix}{connector}{item.name}/")
            extension = "    " if is_last else "│   "
            lines.extend(generate_tree(item, prefix + extension))
        else:
            lines.append(f"{prefix}{connector}{item.name}")
    
    return lines


def collect_files(root: Path) -> list[Path]:
    """收集所有程式碼檔案"""
    files = []
    for path in root.rglob('*'):
        if path.is_file() and not should_ignore(path):
            # 檢查父目錄是否在忽略清單
            if any(p.name in IGNORE_DIRS for p in path.parents):
                continue
            if path.suffix.lower() in CODE_EXTENSIONS or path.name in {'Dockerfile', 'Makefile', 'requirements.txt', 'Procfile'}:
                files.append(path)
    return sorted(files, key=lambda x: str(x).lower())


def bundle_project(target_dir: str, output_file: str = None):
    """主程式：整合專案"""
    root = Path(target_dir).resolve()
    
    if not root.exists():
        print(f"❌ 找不到資料夾: {root}")
        return
    
    if output_file is None:
        output_file = f"{root.name}_bundle.txt"
    
    output_path = Path(output_file).resolve()
    
    with open(output_path, 'w', encoding='utf-8') as out:
        # 標題
        out.write(f"{'='*70}\n")
        out.write(f"專案名稱: {root.name}\n")
        out.write(f"整合時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        out.write(f"{'='*70}\n\n")
        
        # 目錄結構
        out.write("## 目錄結構\n\n")
        out.write("```\n")
        out.write(f"{root.name}/\n")
        for line in generate_tree(root):
            out.write(f"{line}\n")
        out.write("```\n\n")
        
        # 檔案內容
        out.write(f"{'='*70}\n")
        out.write("## 檔案內容\n")
        out.write(f"{'='*70}\n\n")
        
        files = collect_files(root)
        
        for filepath in files:
            rel_path = filepath.relative_to(root)
            out.write(f"\n{'─'*70}\n")
            out.write(f"### {rel_path}\n")
            out.write(f"{'─'*70}\n\n")
            
            # 檢查檔案大小
            if filepath.stat().st_size > MAX_FILE_SIZE:
                out.write(f"（檔案過大，略過內容：{filepath.stat().st_size / 1024:.1f} KB）\n")
                continue
            
            try:
                content = filepath.read_text(encoding='utf-8')
                # 根據副檔名加上 code block
                lang = filepath.suffix.lstrip('.') or 'text'
                if lang == 'txt':
                    lang = 'text'
                out.write(f"```{lang}\n")
                out.write(content)
                if not content.endswith('\n'):
                    out.write('\n')
                out.write("```\n")
            except UnicodeDecodeError:
                out.write("（二進位檔案，略過）\n")
            except Exception as e:
                out.write(f"（讀取錯誤：{e}）\n")
        
        # 統計
        out.write(f"\n{'='*70}\n")
        out.write(f"## 統計\n")
        out.write(f"共 {len(files)} 個檔案\n")
        out.write(f"{'='*70}\n")
    
    print(f"✅ 完成！輸出檔案: {output_path}")
    print(f"   共整合 {len(files)} 個檔案")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        # 預設使用目前目錄
        target = "."
    else:
        target = sys.argv[1]
    
    output = sys.argv[2] if len(sys.argv) > 2 else None
    bundle_project(target, output)
