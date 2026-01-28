#!/usr/bin/env python3
"""
專案整合工具 v2 - 智能分層整理
用途：上傳到 Claude 專案作為 context，結構化便於閱讀
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ===== 設定 =====
IGNORE_DIRS = {'.git', '__pycache__', '.venv', 'venv', 'node_modules', '.idea', '.vscode', 'dist', 'build', '__MACOSX', '.pytest_cache', 'htmlcov'}
IGNORE_FILES = {'.DS_Store', 'Thumbs.db', '*.pyc', '*.pyo', '*.so', '*.egg-info'}
CODE_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.json', '.yaml', '.yml', '.md', '.txt', '.sql', '.sh', '.env.example', '.toml'}

# ===== 檔案大小與截斷規則 =====
FILE_RULES = {
    # 完整保留（不限大小）
    'full': {
        'extensions': {'.md', '.txt', '.toml', '.yaml', '.yml', '.env.example'},
        'files': {'requirements.txt', 'dockerfile', 'makefile', 'procfile'},
    },
    # 程式碼（上限 200KB）
    'code': {
        'extensions': {'.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.sql', '.sh'},
        'max_size': 200 * 1024,
    },
    # 樣式（只取前 150 行）
    'style': {
        'extensions': {'.css', '.scss', '.less'},
        'max_lines': 150,
    },
    # 資料檔（只取前 50 行 + 結構說明）
    'data': {
        'extensions': {'.json', '.csv', '.tsv'},
        'max_lines': 50,
    },
}

# 重要檔案（被跳過時要複製出來）
IMPORTANT_PATTERNS = {
    'extensions': {'.py', '.js', '.ts', '.md', '.html'},
    'files': {'main.py', 'app.py', 'index.py', 'config.py', 'settings.py'},
    'layers': {'entry', 'api', 'core', 'overview'},
}

# ===== 分層定義 =====
# 優先順序：數字越小越前面
LAYER_RULES = {
    # 第 1 層：專案概述
    'overview': {
        'order': 1,
        'title': '📋 專案概述',
        'patterns': ['README*', 'CHANGELOG*', 'LICENSE*', 'docs/*', 'doc/*'],
        'files': {
            # 基本
            'readme.md', 'readme.txt', 'changelog.md', 'license', 'license.md',
            # 開發文檔
            'troubleshooting.md', 'trouble_shooting.md', 'faq.md',
            'architecture.md', 'design.md', 'structure.md',
            'setup.md', 'install.md', 'installation.md',
            'development.md', 'dev.md', 'dev_notes.md', 'notes.md',
            'deployment.md', 'deploy.md',
            'contributing.md', 'contribute.md',
            'api.md', 'api_docs.md', 'endpoints.md',
            'todo.md', 'roadmap.md', 'plan.md',
            'guide.md', 'usage.md', 'manual.md',
            # 中文常見
            '說明.md', '開發筆記.md', '問題排解.md', '架構.md',
        },
    },
    # 第 2 層：設定檔
    'config': {
        'order': 2,
        'title': '⚙️ 設定檔',
        'patterns': ['*.toml', '*.yaml', '*.yml', '.env*', 'config/*', 'settings/*'],
        'files': {'pyproject.toml', 'package.json', 'requirements.txt', 'dockerfile', 'docker-compose.yml', 'makefile', 'procfile', '.env.example', 'config.py', 'settings.py'},
    },
    # 第 3 層：進入點
    'entry': {
        'order': 3,
        'title': '🚀 程式進入點',
        'patterns': [],
        'files': {'main.py', 'app.py', 'index.py', 'server.py', 'run.py', 'index.js', 'index.ts', 'app.js', 'server.js'},
    },
    # 第 4 層：路由/API
    'api': {
        'order': 4,
        'title': '🌐 API / 路由',
        'patterns': ['routes/*', 'routers/*', 'api/*', 'endpoints/*', 'views/*'],
        'files': {'routes.py', 'router.py', 'api.py', 'urls.py'},
    },
    # 第 5 層：資料模型
    'models': {
        'order': 5,
        'title': '📦 資料模型',
        'patterns': ['models/*', 'schemas/*', 'entities/*', 'types/*'],
        'files': {'models.py', 'schemas.py', 'database.py', 'db.py'},
    },
    # 第 6 層：核心邏輯
    'core': {
        'order': 6,
        'title': '🧠 核心邏輯',
        'patterns': ['core/*', 'services/*', 'handlers/*', 'controllers/*', 'lib/*'],
        'files': {'service.py', 'services.py', 'handler.py', 'controller.py'},
    },
    # 第 7 層：工具/輔助
    'utils': {
        'order': 7,
        'title': '🔧 工具 / 輔助',
        'patterns': ['utils/*', 'helpers/*', 'common/*', 'shared/*'],
        'files': {'utils.py', 'helpers.py', 'common.py', 'tools.py'},
    },
    # 第 8 層：前端/靜態
    'frontend': {
        'order': 8,
        'title': '🎨 前端 / 靜態資源',
        'patterns': ['static/*', 'public/*', 'templates/*', 'assets/*', 'frontend/*', 'src/*'],
        'files': set(),
        'extensions': {'.html', '.css', '.js', '.jsx', '.tsx', '.vue', '.svelte'},
    },
    # 第 9 層：測試
    'tests': {
        'order': 9,
        'title': '🧪 測試',
        'patterns': ['tests/*', 'test/*', '__tests__/*', 'spec/*'],
        'files': set(),
    },
    # 第 10 層：其他
    'other': {
        'order': 99,
        'title': '📁 其他檔案',
        'patterns': [],
        'files': set(),
    },
}


def should_ignore(path: Path) -> bool:
    """判斷是否要忽略此路徑"""
    name = path.name
    if name in IGNORE_DIRS or name in IGNORE_FILES:
        return True
    if name.startswith('.') and name not in {'.env.example', '.gitignore'}:
        return True
    for pattern in IGNORE_FILES:
        if '*' in pattern and name.endswith(pattern.replace('*', '')):
            return True
    return False


def match_pattern(rel_path: str, patterns: list) -> bool:
    """檢查路徑是否符合 pattern"""
    rel_lower = rel_path.lower()
    for pattern in patterns:
        pattern_lower = pattern.lower()
        if pattern_lower.endswith('/*'):
            # 資料夾 pattern
            folder = pattern_lower[:-2]
            if rel_lower.startswith(folder + '/') or ('/' + folder + '/') in rel_lower:
                return True
        elif '*' in pattern_lower:
            # 萬用字元
            regex = pattern_lower.replace('*', '.*')
            if re.match(regex, rel_lower):
                return True
        else:
            if rel_lower == pattern_lower:
                return True
    return False


def classify_file(filepath: Path, root: Path) -> str:
    """分類檔案到對應層級"""
    rel_path = str(filepath.relative_to(root))
    filename = filepath.name.lower()
    ext = filepath.suffix.lower()
    
    for layer_id, layer in LAYER_RULES.items():
        # 1. 檢查檔名
        if filename in layer['files']:
            return layer_id
        
        # 2. 檢查路徑 pattern
        if match_pattern(rel_path, layer['patterns']):
            return layer_id
        
        # 3. 檢查副檔名（僅 frontend 層）
        if layer_id == 'frontend' and ext in layer.get('extensions', set()):
            # 但要排除已經被其他規則匹配的
            if '/static/' in rel_path.lower() or '/templates/' in rel_path.lower() or '/public/' in rel_path.lower():
                return layer_id
    
    # 特殊判斷：test 檔案
    if 'test' in filename or filename.startswith('test_') or filename.endswith('_test.py'):
        return 'tests'
    
    return 'other'


def generate_tree(root: Path, prefix: str = "") -> list[str]:
    """產生目錄樹狀圖"""
    lines = []
    try:
        items = sorted(root.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    except PermissionError:
        return lines
    
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
            if any(p.name in IGNORE_DIRS for p in path.parents):
                continue
            if path.suffix.lower() in CODE_EXTENSIONS or path.name.lower() in {'dockerfile', 'makefile', 'requirements.txt', 'procfile', 'license'}:
                files.append(path)
    return files


def estimate_importance(filepath: Path, layer: str) -> str:
    """估算檔案重要度"""
    filename = filepath.name.lower()
    
    # 高重要度
    if layer in ('entry', 'overview'):
        return '⭐⭐⭐'
    if layer == 'config' and filename in {'pyproject.toml', 'package.json', 'requirements.txt'}:
        return '⭐⭐⭐'
    if layer == 'api':
        return '⭐⭐⭐'
    if layer == 'models':
        return '⭐⭐'
    if layer == 'core':
        return '⭐⭐⭐'
    
    # 中重要度
    if layer in ('config', 'models'):
        return '⭐⭐'
    
    # 低重要度
    if layer in ('utils', 'tests', 'other'):
        return '⭐'
    if layer == 'frontend':
        return '⭐'
    
    return '⭐'


def get_file_description(filepath: Path) -> str:
    """嘗試從檔案取得描述（docstring 或第一行註解）"""
    try:
        content = filepath.read_text(encoding='utf-8')
        lines = content.split('\n')
        
        # Python docstring
        if filepath.suffix == '.py':
            for i, line in enumerate(lines[:10]):
                if '"""' in line or "'''" in line:
                    # 單行 docstring
                    match = re.search(r'["\'\s]{3}(.+?)["\'\s]{3}', line)
                    if match:
                        return match.group(1).strip()[:60]
                    # 多行 docstring
                    for j in range(i+1, min(i+5, len(lines))):
                        if lines[j].strip() and not lines[j].strip().startswith(('"""', "'''")):
                            return lines[j].strip()[:60]
                    break
        
        # 第一行註解
        for line in lines[:5]:
            line = line.strip()
            if line.startswith('#') and len(line) > 2:
                return line[1:].strip()[:60]
            if line.startswith('//') and len(line) > 3:
                return line[2:].strip()[:60]
            if line.startswith('/*'):
                return line[2:].replace('*/', '').strip()[:60]
    except:
        pass
    return ''


def get_file_handling(filepath: Path) -> dict:
    """決定檔案的處理方式"""
    ext = filepath.suffix.lower()
    filename = filepath.name.lower()
    
    # 完整保留
    if ext in FILE_RULES['full']['extensions'] or filename in FILE_RULES['full']['files']:
        return {'type': 'full'}
    
    # 樣式檔
    if ext in FILE_RULES['style']['extensions']:
        return {'type': 'truncate_lines', 'max_lines': FILE_RULES['style']['max_lines']}
    
    # 資料檔
    if ext in FILE_RULES['data']['extensions']:
        return {'type': 'truncate_lines', 'max_lines': FILE_RULES['data']['max_lines'], 'show_structure': True}
    
    # 程式碼
    if ext in FILE_RULES['code']['extensions']:
        return {'type': 'size_limit', 'max_size': FILE_RULES['code']['max_size']}
    
    # 預設
    return {'type': 'size_limit', 'max_size': 100 * 1024}


def is_important_file(filepath: Path, layer: str) -> bool:
    """判斷是否為重要檔案"""
    ext = filepath.suffix.lower()
    filename = filepath.name.lower()
    
    if ext in IMPORTANT_PATTERNS['extensions']:
        return True
    if filename in IMPORTANT_PATTERNS['files']:
        return True
    if layer in IMPORTANT_PATTERNS['layers']:
        return True
    return False


def read_file_content(filepath: Path, handling: dict) -> tuple[str, bool, str]:
    """
    讀取檔案內容
    回傳: (內容, 是否被截斷, 截斷原因)
    """
    try:
        file_size = filepath.stat().st_size
        
        if handling['type'] == 'full':
            content = filepath.read_text(encoding='utf-8')
            return content, False, ''
        
        elif handling['type'] == 'size_limit':
            max_size = handling['max_size']
            if file_size > max_size:
                return '', True, f'檔案過大（{file_size/1024:.1f} KB > {max_size/1024:.0f} KB）'
            content = filepath.read_text(encoding='utf-8')
            return content, False, ''
        
        elif handling['type'] == 'truncate_lines':
            max_lines = handling['max_lines']
            content = filepath.read_text(encoding='utf-8')
            lines = content.split('\n')
            
            if len(lines) <= max_lines:
                return content, False, ''
            
            truncated = '\n'.join(lines[:max_lines])
            note = f'\n\n# ... 已截斷（顯示前 {max_lines} 行，共 {len(lines)} 行）...\n'
            
            # JSON 顯示結構
            if handling.get('show_structure') and filepath.suffix.lower() == '.json':
                note += '# 這是資料檔，僅顯示開頭結構供參考\n'
            
            return truncated + note, True, f'僅顯示前 {max_lines} 行'
        
        return '', True, '未知處理類型'
        
    except UnicodeDecodeError:
        return '', True, '二進位檔案'
    except Exception as e:
        return '', True, f'讀取錯誤: {e}'


def bundle_project(target_dir: str, output_file: str = None, split_output: bool = False):
    """主程式：整合專案"""
    root = Path(target_dir).resolve()
    
    if not root.exists():
        print(f"❌ 找不到資料夾: {root}")
        return
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    
    # 建立輸出資料夾（扁平結構）
    output_dir = root / f"for_Claude_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # bundle 檔案放在輸出資料夾內
    bundle_filename = f"{root.name}_bundle_{timestamp}.txt"
    output_path = output_dir / bundle_filename
    
    skipped_files = []  # [(原始相對路徑, 新檔名), ...]
    
    # 收集並分類檔案
    all_files = collect_files(root)
    layers = defaultdict(list)
    
    for f in all_files:
        layer = classify_file(f, root)
        layers[layer].append(f)
    
    # 排序每層內的檔案
    for layer in layers:
        layers[layer].sort(key=lambda x: str(x).lower())
    
    # 開始輸出
    with open(output_path, 'w', encoding='utf-8') as out:
        # ===== 標題 =====
        out.write(f"{'='*70}\n")
        out.write(f"# 專案：{root.name}\n")
        out.write(f"# 整合時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        out.write(f"# 檔案數量：{len(all_files)}\n")
        out.write(f"{'='*70}\n\n")
        
        # ===== 目錄結構 =====
        out.write("## 📂 目錄結構\n\n")
        out.write("```\n")
        out.write(f"{root.name}/\n")
        for line in generate_tree(root):
            out.write(f"{line}\n")
        out.write("```\n\n")
        
        # ===== 檔案索引 =====
        out.write(f"{'='*70}\n")
        out.write("## 📑 檔案索引\n\n")
        out.write("| 層級 | 檔案 | 說明 | 重要度 |\n")
        out.write("|------|------|------|--------|\n")
        
        sorted_layers = sorted(LAYER_RULES.items(), key=lambda x: x[1]['order'])
        for layer_id, layer_info in sorted_layers:
            if layer_id not in layers:
                continue
            for f in layers[layer_id]:
                rel = f.relative_to(root)
                desc = get_file_description(f)
                importance = estimate_importance(f, layer_id)
                layer_emoji = layer_info['title'].split()[0]
                out.write(f"| {layer_emoji} | `{rel}` | {desc} | {importance} |\n")
        out.write("\n")
        
        # ===== 分層內容 =====
        for layer_id, layer_info in sorted_layers:
            if layer_id not in layers:
                continue
            
            out.write(f"\n{'='*70}\n")
            out.write(f"## {layer_info['title']}\n")
            out.write(f"{'='*70}\n")
            
            for filepath in layers[layer_id]:
                rel_path = filepath.relative_to(root)
                importance = estimate_importance(filepath, layer_id)
                desc = get_file_description(filepath)
                handling = get_file_handling(filepath)
                
                out.write(f"\n{'─'*70}\n")
                out.write(f"### 📄 {rel_path}  {importance}\n")
                if desc:
                    out.write(f"> {desc}\n")
                out.write(f"{'─'*70}\n\n")
                
                # 讀取內容
                content, was_skipped, skip_reason = read_file_content(filepath, handling)
                
                if was_skipped:
                    out.write(f"⚠️ {skip_reason}\n")
                    
                    # 重要檔案複製到輸出資料夾（扁平化，用 -- 取代 /）
                    if is_important_file(filepath, layer_id):
                        # 把路徑轉成檔名：api/routes/auth.py → api--routes--auth.py
                        flat_name = str(rel_path).replace('/', '--').replace('\\', '--')
                        dest = output_dir / flat_name
                        shutil.copy2(filepath, dest)
                        skipped_files.append((rel_path, flat_name))
                        out.write(f"📁 已複製: {flat_name}\n")
                else:
                    lang = filepath.suffix.lstrip('.') or 'text'
                    lang_map = {'txt': 'text', 'yml': 'yaml'}
                    lang = lang_map.get(lang, lang)
                    
                    out.write(f"```{lang}\n")
                    out.write(content)
                    if not content.endswith('\n'):
                        out.write('\n')
                    out.write("```\n")
        
        # ===== 統計 =====
        out.write(f"\n{'='*70}\n")
        out.write("## 📊 統計\n\n")
        for layer_id, layer_info in sorted_layers:
            if layer_id in layers:
                out.write(f"- {layer_info['title']}：{len(layers[layer_id])} 個檔案\n")
        out.write(f"\n**總計：{len(all_files)} 個檔案**\n")
        
        if skipped_files:
            out.write(f"\n### ⚠️ 被跳過的重要檔案（已複製到此資料夾）\n\n")
            out.write("| 原始路徑 | 檔名 |\n")
            out.write("|----------|------|\n")
            for orig, flat in skipped_files:
                out.write(f"| `{orig}` | `{flat}` |\n")
        
        out.write(f"{'='*70}\n")
    
    # 列出資料夾內容
    all_output_files = list(output_dir.iterdir())
    
    print(f"\n{'='*50}")
    print(f"✅ 完成！")
    print(f"{'='*50}")
    print(f"\n📁 輸出資料夾: {output_dir}")
    print(f"\n   請全選以下 {len(all_output_files)} 個檔案上傳到 Claude:")
    for f in sorted(all_output_files, key=lambda x: (not x.name.endswith('.txt'), x.name)):
        print(f"   • {f.name}")
    
    if skipped_files:
        print(f"\n   💡 檔名中的 '--' 代表原本的資料夾層級")
        print(f"      例如: api--routes--auth.py = api/routes/auth.py")
    
    print(f"\n📊 分層統計:")
    for layer_id, layer_info in sorted_layers:
        if layer_id in layers:
            print(f"   {layer_info['title']}：{len(layers[layer_id])} 個")


if __name__ == "__main__":
    import sys
    
    print("=" * 50)
    print("📦 專案整合工具 v2")
    print("=" * 50)
    
    if len(sys.argv) < 2:
        target = "."
        print(f"使用目前目錄: {Path(target).resolve()}")
    else:
        target = sys.argv[1]
    
    output = sys.argv[2] if len(sys.argv) > 2 else None
    bundle_project(target, output)
