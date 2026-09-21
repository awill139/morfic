import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from morfic.inspector import inspect_repo
from morfic.planner import heuristic_plan
from morfic.runtimes import dotnet_executable


def test_compose_detection():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'docker-compose.yml').write_text('''services:\n  web:\n    image: example/web\n    ports:\n      - "8123:8080"\n  db:\n    image: postgres:16\n''')
        (root/'README.md').write_text('Family web app')
        plan=heuristic_plan(root, inspect_repo(root))
        assert plan.project_type=='docker'
        assert plan.compose_file=='docker-compose.yml'
        assert plan.port==8123
        assert plan.frontend.kind=='existing'


def test_dotnet_detection():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'FamilyApp.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk.Web"></Project>')
        (root/'README.md').write_text('ASP.NET web app available at http://localhost:5055')
        plan=heuristic_plan(root, inspect_repo(root))
        assert plan.project_type=='dotnet'
        assert plan.port==5055
        assert plan.run_command[:4]==['dotnet','run','--project','FamilyApp.csproj']
        assert plan.install_commands==[['dotnet','restore','FamilyApp.csproj']]
        assert plan.frontend.kind=='existing'


def test_managed_dotnet_precedence():
    with TemporaryDirectory() as td:
        fake=Path(td)/'dotnet'
        fake.write_text('')
        fake.chmod(0o755)
        # dotnet_executable supports a system SDK when no managed runtime exists.
        with patch('morfic.runtimes.shutil.which', return_value=str(fake)):
            assert dotnet_executable()==str(fake)


if __name__=='__main__':
    test_compose_detection(); test_dotnet_detection(); test_managed_dotnet_precedence()
    print('COMPLEX RUNTIMES PASS: compose + dotnet planning')
