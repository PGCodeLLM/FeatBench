import subprocess
import logging
import re
import shlex
import time
from typing import Tuple, Optional
import docker
from abc import ABC, abstractmethod
import pty
import os
import select
import fcntl
import signal

from docker_agent.core.types import Container
from docker_agent.config.config import DOCKER_ENVIRONMENT
from docker_agent.core.exceptions import TestExecutionError

# Strip ANSI CSI escape sequences (colors, cursor movement, etc.) from
# streamed exec output before writing it to exec.log so the file is
# human-readable.
_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

class BaseCommandExecutor(ABC):
    """Command executor base class"""
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.env = None  # Subclasses override if needed

    def _set_timeout(self, timeout, process=None):
        """Set timeout handling"""
        if timeout is not None:
            def timeout_handler(signum, frame):
                if process is not None:
                    process.terminate()
                raise TestExecutionError(f"Command execution timeout after {timeout}s")
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout)

    def _cancel_timeout(self, timeout):
        """Cancel timeout handling"""
        if timeout is not None:
            signal.alarm(0)

    @abstractmethod
    def execute(self, command: str, workdir: str, stream: bool = False, tty: bool = True, timeout: Optional[float] = None) -> Tuple[int, str]:
        """Execute command"""
        pass
    
    @abstractmethod
    def _execute_pty(self, command: str, workdir: str, stream: bool, timeout: Optional[float]) -> Tuple[int, str]:
        """Execute command in PTY mode for streaming"""
        pass

    @abstractmethod
    def _execute_without_pty(self, command: str, workdir: str, stream: bool, timeout: Optional[float]) -> Tuple[int, str]:
        """Execute command without PTY mode"""
        pass


class LocalCommandExecutor(BaseCommandExecutor):
    """Local command executor"""
    def __init__(self):
        super().__init__()
        env = dict(os.environ)
        env.update(DOCKER_ENVIRONMENT)
        self.env = env

    def execute(self, command: str, workdir: str = "/", stream: bool = False, tty: bool = True, timeout: Optional[float] = None) -> Tuple[int, str]:
        """Execute command locally"""
        try:
            if tty:
                return self._execute_pty(command, workdir, stream, timeout)
            else:
                return self._execute_without_pty(command, workdir, stream, timeout)
        except Exception as e:
            self.logger.error(f"Local command execution error: {e}")
            return 1, str(e)

    def _setup_pty_process(self, command: str, workdir: str):
        """Setup PTY process and return (master_fd, slave_fd, process)"""
        master_fd, slave_fd = pty.openpty()
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=workdir,
            stdout=slave_fd,
            stderr=slave_fd,
            stdin=slave_fd,
            preexec_fn=os.setsid,
            env=self.env
        )
        os.close(slave_fd)
        return master_fd, process

    def _execute_pty(self, command: str, workdir: str, stream: bool, timeout: Optional[float]) -> Tuple[int, str]:
        """Execute local command in streaming mode"""
        self.logger.info(f"Local pty execute command: {command}")
        master_fd, process = self._setup_pty_process(command, workdir)
        
        self._set_timeout(timeout, process)
        try:
            if stream:
                # Set non-blocking read
                fcntl.fcntl(master_fd, fcntl.F_SETFL, os.O_NONBLOCK)
                output_lines = []
                
                while True:
                    if process.poll() is not None:
                        try:
                            remaining = os.read(master_fd, 4096).decode('utf-8', errors='replace')
                            if remaining:
                                output_lines.append(remaining)
                        except (OSError, BlockingIOError):
                            pass
                        break
                    
                    ready, _, _ = select.select([master_fd], [], [], 0.1)
                    if ready:
                        try:
                            data = os.read(master_fd, 4096)
                            if data:
                                text = data.decode('utf-8', errors='replace')
                                output_lines.append(text)
                        except (OSError, BlockingIOError):
                            continue
                
                process.wait()
                return process.returncode, ''.join(output_lines)
            else:
                output = b""
                while True:
                    try:
                        data = os.read(master_fd, 4096)
                        if not data:
                            break
                        output += data
                    except OSError:
                        break
                    if process.poll() is not None:
                        try:
                            while True:
                                data = os.read(master_fd, 4096)
                                if not data:
                                    break
                                output += data
                        except OSError:
                            pass
                        break
                process.wait()
                output = output.decode('utf-8', errors='replace')
                return process.returncode, output
        finally:
            try:
                os.close(master_fd)
                self._cancel_timeout(timeout)
            except OSError:
                pass
    
    def _execute_without_pty(self, command: str, workdir: str, stream: bool, timeout: Optional[float]) -> Tuple[int, str]:
        """Streaming execution method without PTY"""
        self.logger.info(f"Local execute command: {command}")
        if stream:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                bufsize=0,  # No buffering
                universal_newlines=True,
                env=self.env
            )
            
            self._set_timeout(timeout, process)
            output_lines = []
            try:
                for line in process.stdout:
                    self.logger.debug(f"Command output: {line.rstrip()}")
                    output_lines.append(line)
                
                process.wait()
                return process.returncode, ''.join(output_lines)
            finally:
                self._cancel_timeout(timeout)
        else:
            if timeout is not None:
                try:
                    result = subprocess.run(
                        command,
                        shell=True,
                        cwd=workdir,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        timeout=timeout,
                        env=self.env
                    )
                except subprocess.TimeoutExpired:
                    raise TestExecutionError(f"Command execution timeout after {timeout}s")
            else:
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    env=self.env
                )
            output = result.stdout + result.stderr
            return result.returncode, output


class DockerCommandExecutor(BaseCommandExecutor):
    """Docker container command executor"""

    def __init__(self, container: Container, log_dir=None):
        super().__init__()
        self.container = container
        self.client = docker.from_env(timeout=3700)  # Must exceed the 3600s container-side timeout
        self._exec_log_path = log_dir / "exec.log" if log_dir else None

    def execute(self, command: str, workdir: str = "/workdir", stream: bool = False, tty: bool = True, timeout: Optional[float] = 3600) -> Tuple[int, str]:
        """Execute command in Docker container"""
        try:
            if tty:
                return self._execute_pty(command, workdir, stream, timeout)
            else:
                return self._execute_without_pty(command, workdir, stream, timeout)
        except TestExecutionError:
            raise  # Let timeout errors propagate
        except Exception as e:
            self.logger.error(f"Docker command execution error: {e}")
            return 1, str(e)

    def _exec(self, command: str, workdir: str, stream: bool, tty: bool, timeout: Optional[float]) -> Tuple[int, str]:
        """Common execution logic"""
        if timeout is not None:
            timeout_command = f"timeout -s TERM -k 10s {int(timeout)}s bash -c {shlex.quote(command)}"
        else:
            timeout_command = command

        start_time = time.monotonic()

        exec_instance = self.client.api.exec_create(
            self.container.id,
            cmd=["/bin/bash", "-c", timeout_command],
            workdir=workdir,
            stdout=True,
            stderr=True,
            tty=tty,
            environment=self.env
        )
        output_stream = self.client.api.exec_start(exec_instance['Id'], stream=stream, tty=tty)

        if stream:
            output_lines = []
            log_fh = None
            if self._exec_log_path:
                try:
                    log_fh = open(self._exec_log_path, "a", encoding="utf-8")
                except Exception as e:
                    self.logger.warning(f"Could not open {self._exec_log_path}: {e}")
            try:
                for chunk in output_stream:
                    line_str = chunk.decode('utf-8', errors='replace')
                    output_lines.append(line_str)
                    if log_fh is not None:
                        # Strip ANSI escapes and CR so the log is readable.
                        clean = _ANSI_ESCAPE_RE.sub('', line_str).replace('\r', '')
                        log_fh.write(clean)
            except Exception as e:
                self.logger.warning(f"Stream interrupted: {e}. Preserving {len(output_lines)} captured chunks.")
            finally:
                if log_fh is not None:
                    try:
                        log_fh.close()
                    except Exception:
                        pass

            try:
                exit_code = self.client.api.exec_inspect(exec_instance['Id'])['ExitCode']
            except Exception:
                exit_code = 1

            output = ''.join(output_lines)

            if timeout is not None and exit_code in (124, 137):
                elapsed = time.monotonic() - start_time
                # Only treat as our timeout if enough wall-clock time actually
                # passed (within 90% of the configured timeout). Otherwise the
                # child process itself was killed (e.g. OOM) and just happens
                # to share exit code 124/137.
                if elapsed >= timeout * 0.9:
                    raise TestExecutionError(f"Container command execution timeout after {elapsed:.0f}s (limit {timeout}s)")
                else:
                    self.logger.warning(
                        f"Process exited with code {exit_code} after {elapsed:.0f}s "
                        f"(timeout is {timeout}s) — not a timeout, likely OOM or signal kill"
                    )

            return exit_code, output
        else:
            output = output_stream.decode('utf-8', errors='replace')

            exit_code = self.client.api.exec_inspect(exec_instance['Id'])['ExitCode']
            if timeout is not None and exit_code in (124, 137):
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout * 0.9:
                    raise TestExecutionError(f"Container command execution timeout after {elapsed:.0f}s (limit {timeout}s)")

            return exit_code, output

    def _execute_pty(self, command: str, workdir: str, stream: bool, timeout: Optional[float]) -> Tuple[int, str]:
        self.logger.info(f"Docker container pty execute command: {command}")
        return self._exec(command, workdir, stream, True, timeout)

    def _execute_without_pty(self, command: str, workdir: str, stream: bool, timeout: Optional[float]) -> Tuple[int, str]:
        self.logger.info(f"Docker container execute command: {command}")
        return self._exec(command, workdir, stream, False, timeout)