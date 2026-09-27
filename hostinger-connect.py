#!/usr/bin/env python3
"""Install the GitHub Actions runner for the Anexxo migration."""
import termios
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import urllib.request

RUNNER_DIR = pathlib.Path("/home/actions/actions-runner")
PACKAGE = pathlib.Path("/tmp/anexxo-runner-2.337.0.tar.gz")
SHA256 = "70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613"
DOWNLOAD = "https://github.com/actions/runner/releases/download/v2.337.0/actions-runner-linux-x64-2.337.0.tar.gz"
REPOSITORY = "https://github.com/rachidsader-tech/central-eventos"

def run(args, **kwargs):
    subprocess.run(args, check=True, **kwargs)

def digest(path):
    if not path.is_file():
        return ""
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()

def main():
    if os.geteuid() != 0:
        raise RuntimeError("Abra o terminal da Hostinger como root.")
    if os.uname().machine != "x86_64":
        raise RuntimeError("Este instalador exige um servidor x64.")
    if subprocess.run(["id", "actions"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        run(["useradd", "--create-home", "--shell", "/bin/bash", "actions"])
    RUNNER_DIR.mkdir(parents=True, exist_ok=True)
    os.chdir(RUNNER_DIR)
    if not (RUNNER_DIR / ".runner").exists():
        if digest(PACKAGE) != SHA256:
            previous = pathlib.Path("/tmp/actions-runner.tar.gz")
            if digest(previous) == SHA256:
                package = previous
            else:
                print("Baixando a conexao oficial do GitHub...", flush=True)
                urllib.request.urlretrieve(DOWNLOAD, PACKAGE)
                package = PACKAGE
        else:
            package = PACKAGE
        if digest(package) != SHA256:
            raise RuntimeError("O arquivo baixado nao passou na verificacao.")
        run(["tar", "-xzf", str(package), "-C", str(RUNNER_DIR)])
        print("Verificando dependencias...", flush=True)
        run(["bash", "./bin/installdependencies.sh"], env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"))
        run(["chown", "-R", "actions:actions", str(RUNNER_DIR)])
        print("\nNa pagina do GitHub, copie o codigo depois de --token.", flush=True)
        terminal_settings = None
        try:
            terminal_settings = termios.tcgetattr(sys.stdin.fileno())
            hidden = terminal_settings.copy()
            hidden[3] &= ~termios.ECHO
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, hidden)
        except (OSError, ValueError):
            terminal_settings = None
        try:
            token = input("Cole o codigo aqui e pressione Enter: ").strip()
        finally:
            if terminal_settings is not None:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, terminal_settings)
            print("\n\x1b[2J\x1b[H", end="", flush=True)
        match = re.search(r"--token\s+([A-Za-z0-9_-]+)", token)
        if match:
            token = match.group(1)
        if not re.fullmatch(r"[A-Za-z0-9_-]{15,200}", token):
            raise RuntimeError("O codigo nao foi recebido corretamente. Execute o instalador novamente.")
        result = subprocess.run([
            "runuser", "-u", "actions", "--", "./config.sh",
            "--url", REPOSITORY, "--token", token, "--unattended",
            "--name", "anexxo-vps", "--labels", "anexxo-vps",
        ])
        token = None
        if result.returncode:
            raise RuntimeError("O GitHub nao concluiu a conexao. Envie apenas a mensagem de erro acima.")
    if not (RUNNER_DIR / ".service").exists():
        run(["./svc.sh", "install", "actions"])
    service = (RUNNER_DIR / ".service").read_text().strip()
    if not re.fullmatch(r"actions\.runner\.[A-Za-z0-9_.@-]+\.service", service):
        raise RuntimeError("Nome inesperado do servico.")
    run(["systemctl", "enable", "--now", service])
    run(["systemctl", "is-active", "--quiet", service])
    print("\nCONEXAO INSTALADA. Avise no chat: pronto.", flush=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInstalacao interrompida.")
        sys.exit(1)
    except Exception as error:
        if isinstance(error, RuntimeError):
            print("\nERRO:", error)
        elif isinstance(error, subprocess.CalledProcessError):
            print("\nERRO: uma etapa falhou; veja a mensagem imediatamente acima.")
        else:
            print("\nERRO:", type(error).__name__, "- envie a parte final da tela, sem codigos.")
        sys.exit(1)
