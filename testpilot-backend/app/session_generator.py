"""登录会话生成器：根据配置的凭证和选择器，自动执行 Playwright 登录脚本，保存 storageState"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from .config import get_settings, Settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def _build_locator(selector: str, selector_type: str) -> str:
    """根据选择器类型生成 Playwright locator 代码"""
    if not selector:
        return ""
    st = (selector_type or "css").lower()
    # 转义单引号
    safe = selector.replace("'", "\\'")
    if st == "css":
        return f"page.locator('{safe}')"
    if st == "placeholder":
        return f"page.getByPlaceholder('{safe}')"
    if st == "locator":
        # 用户直接填写 Playwright locator 表达式，如 getByRole('button', { name: '登录' })
        return f"page.{selector}"
    # 默认当 css
    return f"page.locator('{safe}')"


def _build_success_check(indicator: str, indicator_type: str) -> str:
    """生成登录成功的判断代码"""
    if not indicator:
        # 默认等待 networkidle
        return "await page.waitForLoadState('networkidle', { timeout: 15000 });"
    it = (indicator_type or "url").lower()
    safe = indicator.replace("'", "\\'")
    if it == "url":
        # 完整 URL 前缀匹配（能匹配 /dashboard 和 /dashboard/tasks）；路径用 **/path**
        if safe.startswith(("http://", "https://")):
            return f"await page.waitForURL('{safe}**', {{ timeout: 15000 }});"
        else:
            return f"await page.waitForURL('**{safe}**', {{ timeout: 15000 }});"
    if it == "css":
        return f"await page.locator('{safe}').waitFor({{ state: 'visible', timeout: 15000 }});"
    if it == "placeholder":
        return f"await page.getByPlaceholder('{safe}').waitFor({{ state: 'visible', timeout: 15000 }});"
    if it == "locator":
        return f"await page.{indicator}.waitFor({{ state: 'visible', timeout: 15000 }});"
    return "await page.waitForLoadState('networkidle', { timeout: 15000 });"


def generate_custom_script(
    custom_script: str,
    storage_state_path: str,
) -> str:
    """
    包装用户自定义的 Playwright 登录代码，自动追加 storageState 保存逻辑。

    用户脚本中可使用 `page` 对象执行任意操作。系统会自动在末尾追加：
      await page.context().storageState({ path: '...' });

    用户脚本示例：
      await page.goto('http://localhost:3000/login');
      await page.getByPlaceholder('用户名').fill('admin');
      await page.getByPlaceholder('密码').fill('pwd123');
      await page.getByRole('button', { name: '登录' }).click();
      await page.waitForURL('**/dashboard**');
    """
    # 转义路径中的反斜杠（Windows 路径）
    safe_storage_path = storage_state_path.replace("\\", "/")

    # 去除用户脚本首尾空白，确保末尾有分号
    user_code = custom_script.strip()
    if user_code and not user_code.endswith((";", "}")):
        user_code += ";"

    script = f"""import {{ test, expect }} from '@playwright/test';

test('生成登录会话快照（自定义脚本）', async ({{ page }}) => {{
  // ===== 用户自定义登录代码 开始 =====
  {user_code}
  // ===== 用户自定义登录代码 结束 =====

  // 自动追加：保存会话快照
  await page.context().storageState({{ path: '{safe_storage_path}' }});
}});
"""
    return script


def generate_login_script(
    login_url: str,
    username: str,
    password: str,
    username_selector: str,
    username_selector_type: str,
    password_selector: str,
    password_selector_type: str,
    submit_selector: str,
    submit_selector_type: str,
    success_indicator: str,
    success_indicator_type: str,
    storage_state_path: str,
    browser_type: str = "chromium",
) -> str:
    """生成 Playwright 登录脚本（TypeScript）"""
    username_loc = _build_locator(username_selector, username_selector_type) or "page.getByPlaceholder(/用户名|邮箱|email|username/i)"
    password_loc = _build_locator(password_selector, password_selector_type) or "page.getByPlaceholder(/密码|password/i)"
    submit_loc = _build_locator(submit_selector, submit_selector_type) or "page.getByRole('button', { name: /登录|sign in|log in/i })"
    success_check = _build_success_check(success_indicator, success_indicator_type)

    # 转义路径中的反斜杠（Windows 路径）
    safe_storage_path = storage_state_path.replace("\\", "/")
    # 转义凭证和 URL 中的单引号，防止 JS 语法错误
    safe_login_url = (login_url or "").replace("'", "\\'")
    safe_username = (username or "").replace("'", "\\'")
    safe_password = (password or "").replace("'", "\\'")

    script = f"""import {{ test, expect }} from '@playwright/test';

test('生成登录会话快照', async ({{ page }}) => {{
  // 1. 访问登录页（用 networkidle 确保 Next.js/React 完成 hydration，否则表单状态不生效）
  await page.goto('{safe_login_url}', {{ waitUntil: 'networkidle' }});

  // 2. 填入凭证（先等待元素可交互）
  await ({username_loc}).waitFor({{ state: 'visible', timeout: 10000 }});
  await ({username_loc}).fill('{safe_username}');
  await ({password_loc}).fill('{safe_password}');

  // 3. 点击提交
  await ({submit_loc}).click();

  // 4. 等待登录成功
  {success_check}

  // 5. 保存会话快照
  await page.context().storageState({{ path: '{safe_storage_path}' }});
}});
"""
    return script


class LoginSessionGenerator:
    """登录会话生成器：执行登录脚本，保存 storageState 文件"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _get_storage_dir(self, project_id: int) -> Path:
        """获取项目的 storageState 文件目录"""
        storage_dir = self.settings.base_dir / "data" / "storage-states" / str(project_id)
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir

    def _write_config(self, work_dir: Path) -> str:
        """写入 playwright.config.ts（不使用 storageState，因为这是生成会话的过程）"""
        # 显式设置 testDir 为 work_dir，避免 Playwright 扫描到项目根目录下的其他 spec 文件
        # 使用绝对路径确保跨目录运行时正确解析
        safe_work_dir = str(work_dir).replace("\\", "/")
        
        # 检查代理配置
        proxy_config = ""
        import os
        proxy_server = os.environ.get("PLAYWRIGHT_PROXY_SERVER")
        proxy_username = os.environ.get("PLAYWRIGHT_PROXY_USERNAME")
        proxy_password = os.environ.get("PLAYWRIGHT_PROXY_PASSWORD")
        if proxy_server:
            proxy_parts = [f"server: '{proxy_server}'"]
            if proxy_username:
                proxy_parts.append(f"username: '{proxy_username}'")
            if proxy_password:
                proxy_parts.append(f"password: '{proxy_password}'")
            proxy_config = f"\n    proxy: {{{', '.join(proxy_parts)}}},"
        
        config_content = f"""import {{ defineConfig }} from '@playwright/test';

export default defineConfig({{
  testDir: '{safe_work_dir}',
  outputDir: '.test-results',
  use: {{
    browserName: '{self.settings.browser_type}',
    screenshot: 'on',
    video: 'retain-on-failure',{proxy_config}
  }},
}});
"""
        config_path = work_dir / "playwright.config.ts"
        config_path.write_text(config_content, encoding="utf-8")
        return str(config_path)

    def _build_command(self, spec_rel_path: str, work_dir: Path, timeout: int | None) -> list[str]:
        """构建 playwright test 命令"""
        npx = shutil.which("npx")
        if not npx:
            raise FileNotFoundError("npx")

        config_rel = Path(self._write_config(work_dir)).relative_to(self.settings.playwright_root).as_posix()
        # 不再传 spec_rel_path 作为位置参数（坐标系不一致会导致运行错误的 spec）
        # 改为仅用 --config，由 config 的 testDir 限定运行范围
        cmd = [npx, "playwright", "test", "--reporter=line", "--config", config_rel]
        if timeout:
            cmd.extend(["--timeout", str(timeout)])
        return cmd

    async def generate_session(
        self,
        profile,
        project_id: int,
        app_url: str | None = None,
        timeout: int | None = 60000,
    ) -> dict:
        """
        执行登录脚本，生成 storageState 文件

        :param profile: LoginProfile ORM 对象
        :param project_id: 项目 ID
        :param app_url: 项目配置的应用 URL（作为 login_url 的默认值）
        :param timeout: 超时时间（毫秒）
        :return: { success, storage_state_path, error, stdout, stderr, screenshots }
        """
        # 校验必要参数
        login_url = profile.login_url or app_url
        if not login_url:
            return {
                "success": False,
                "error": "未配置登录页URL，且项目未配置应用URL",
                "storageStatePath": None,
            }
        if not profile.username or not profile.password:
            return {
                "success": False,
                "error": "未配置账号或密码",
                "storageStatePath": None,
            }

        # 确定 storageState 文件路径
        storage_dir = self._get_storage_dir(project_id)
        storage_file = storage_dir / f"profile-{profile.id}.json"
        storage_state_path = str(storage_file)

        # 根据脚本模式生成登录脚本
        script_mode = (profile.script_mode or "form").lower()
        if script_mode == "custom" and profile.custom_script:
            # 自定义脚本模式：直接使用用户提供的 Playwright 代码
            script = generate_custom_script(
                custom_script=profile.custom_script,
                storage_state_path=storage_state_path,
            )
        else:
            # 表单模式：根据选择器生成脚本
            script = generate_login_script(
                login_url=login_url,
                username=profile.username,
                password=profile.password,
                username_selector=profile.username_selector,
                username_selector_type=profile.username_selector_type,
                password_selector=profile.password_selector,
                password_selector_type=profile.password_selector_type,
                submit_selector=profile.submit_selector,
                submit_selector_type=profile.submit_selector_type,
                success_indicator=profile.success_indicator,
                success_indicator_type=profile.success_indicator_type,
                storage_state_path=storage_state_path,
                browser_type=self.settings.browser_type,
            )

        logger.debug(f"生成登录脚本（profile #{profile.id}）:\n{script}")

        # 准备执行目录
        playwright_root = self.settings.playwright_root
        run_dir = self.settings.runtime_dir / uuid.uuid4().hex[:8]
        run_dir.mkdir(parents=True, exist_ok=True)
        spec_file = run_dir / "test.spec.ts"
        spec_file.write_text(script, encoding="utf-8")

        spec_rel = spec_file.relative_to(playwright_root).as_posix()
        cmd = self._build_command(spec_rel, run_dir, timeout)
        proc_timeout = int((timeout or 60000) / 1000 + 60)

        logger.info(f"[SESSION-GEN] 开始执行登录脚本")
        logger.info(f"[SESSION-GEN] 命令: {' '.join(cmd)}")
        logger.info(f"[SESSION-GEN] 工作目录: {playwright_root}")
        logger.info(f"[SESSION-GEN] 脚本文件: {spec_file}")
        logger.info(f"[SESSION-GEN] 超时时间: {proc_timeout}s")

        start = time.time()
        try:
            logger.info(f"[SESSION-GEN] 启动 subprocess...")
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=proc_timeout,
                cwd=str(playwright_root),
            )
            logger.info(f"[SESSION-GEN] subprocess 完成，返回码: {proc.returncode}")
            logger.info(f"[SESSION-GEN] 执行耗时: {int((time.time() - start) * 1000)}ms")
            duration_ms = int((time.time() - start) * 1000)
            success = proc.returncode == 0 and storage_file.exists()

            # 归一化子进程输出：subprocess 可能返回 None，需避免下游 len()/拼接报错
            stdout_text = proc.stdout or ""
            stderr_text = proc.stderr or ""

            # 收集截图
            screenshots = []
            for pattern in ["*.png", "test-results/**/*.png", ".test-results/**/*.png"]:
                screenshots.extend(str(p) for p in run_dir.glob(pattern))

            error_info = None if success else self._extract_error(stderr_text, stdout_text)

            result = {
                "success": success,
                "storageStatePath": storage_state_path if success else None,
                "duration_ms": duration_ms,
                "stdout": stdout_text[-4000:] if len(stdout_text) > 4000 else stdout_text,
                "stderr": stderr_text[-4000:] if len(stderr_text) > 4000 else stderr_text,
                "screenshots": screenshots,
                "error": error_info,
            }
            if not success and not error_info:
                if not storage_file.exists():
                    result["error"] = {
                        "type": "login_failed",
                        "message": "登录脚本执行完成，但 storageState 文件未生成",
                        "suggestion": "可能登录失败，请检查账号密码是否正确，或登录成功后的跳转是否符合预期",
                        "details": []
                    }
                else:
                    result["error"] = {
                        "type": "unknown",
                        "message": "登录脚本执行失败",
                        "suggestion": "请检查登录页面URL和选择器配置是否正确",
                        "details": []
                    }
            return result
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            return {
                "success": False,
                "storageStatePath": None,
                "duration_ms": duration_ms,
                "stdout": "",
                "stderr": "执行超时",
                "screenshots": [],
                "error": {
                    "type": "timeout",
                    "message": f"登录脚本执行超时（{proc_timeout}s）",
                    "suggestion": "脚本执行时间过长，请检查网络连接或登录页面响应速度",
                    "details": []
                },
            }
        except FileNotFoundError:
            return {
                "success": False,
                "storageStatePath": None,
                "duration_ms": 0,
                "stdout": "",
                "stderr": "未找到 npx 命令",
                "screenshots": [],
                "error": "环境错误：未安装 Node.js 或 npx 不在 PATH 中",
            }
        except Exception as e:
            logger.error(f"生成会话异常: {type(e).__name__}: {e}", exc_info=True)
            return {
                "success": False,
                "storageStatePath": None,
                "duration_ms": 0,
                "stdout": "",
                "stderr": str(e),
                "screenshots": [],
                "error": f"生成会话异常: {type(e).__name__}: {e}",
            }

    @staticmethod
    def _extract_error(stderr: str, stdout: str) -> dict:
        """从输出中提取关键错误信息，并分类为选择器问题或其他问题"""
        # 归一化：子进程输出可能为 None，避免拼接/切分报错
        stderr = stderr or ""
        stdout = stdout or ""
        full_output = stderr + "\n" + stdout
        lines = full_output.split("\n")
        
        error_info = {
            "type": "unknown",
            "message": "登录脚本执行失败",
            "suggestion": "请检查登录页面URL和选择器配置是否正确",
            "details": []
        }
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if any(kw in line.lower() for kw in ["error", "failed", "timeout", "locator", "not found", "exception"]):
                error_info["details"].append(line)
                if len(error_info["details"]) >= 5:
                    break
        
        details_str = "\n".join(error_info["details"])
        
        if "locator.waitFor" in details_str or "getByPlaceholder" in details_str:
            error_info["type"] = "selector"
            if "username" in details_str.lower() or "邮箱" in details_str or "email" in details_str:
                error_info["message"] = "无法找到用户名输入框"
                error_info["suggestion"] = "请检查登录页面上的用户名输入框，确认其 placeholder 包含「用户名」「邮箱」「email」「username」等关键词，或在选择器配置中手动指定用户名输入框的选择器"
            elif "password" in details_str.lower():
                error_info["message"] = "无法找到密码输入框"
                error_info["suggestion"] = "请检查登录页面上的密码输入框，确认其 placeholder 包含「密码」「password」等关键词，或在选择器配置中手动指定密码输入框的选择器"
            elif "button" in details_str.lower() or "submit" in details_str.lower():
                error_info["message"] = "无法找到登录按钮"
                error_info["suggestion"] = "请检查登录页面上的登录按钮，确认其包含「登录」「sign in」「log in」等文字，或在选择器配置中手动指定登录按钮的选择器"
            else:
                error_info["message"] = "无法定位页面元素"
                error_info["suggestion"] = "请检查登录页面URL是否正确，页面是否能正常加载，以及选择器配置是否正确"
        elif "TimeoutError" in details_str:
            error_info["type"] = "timeout"
            if "waitForURL" in details_str:
                error_info["message"] = "登录后跳转超时"
                error_info["suggestion"] = "请检查登录成功后的跳转URL是否正确，或延长成功判断的超时时间。可能原因：登录失败、跳转URL配置错误、网络延迟"
            else:
                error_info["message"] = "操作超时"
                error_info["suggestion"] = "页面加载或操作超时，请检查网络连接或登录页面响应速度"
        elif "Error: page.goto" in details_str or "net::ERR" in details_str:
            error_info["type"] = "network"
            error_info["message"] = "无法访问登录页面"
            error_info["suggestion"] = "请检查登录页面URL是否正确，网络是否能访问该地址"
        elif "fill" in details_str and ("not visible" in details_str or "disabled" in details_str):
            error_info["type"] = "interaction"
            error_info["message"] = "无法填写表单"
            error_info["suggestion"] = "输入框可能被遮挡、不可见或被禁用，请检查登录页面的表单状态"
        
        if not error_info["details"]:
            error_info["message"] = "登录脚本执行失败，请检查凭证和选择器配置"
        
        return error_info
