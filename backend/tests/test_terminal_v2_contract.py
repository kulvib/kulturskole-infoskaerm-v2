from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class TerminalV2ContractTests(unittest.TestCase):
    def test_python_sources_parse(self) -> None:
        for path in (
            "service1/terminal_v2.py",
            "service1/terminal_websocket_auth.py",
            "service1/client_domain_models.py",
            "service1/terminal_v2_models.py",
            "service1/routers/terminal_auth.py",
            "service1/routers/client_auth_compat.py",
            "service1/routers/terminal.py",
            "service1/routers/livestream_v2.py",
            "tests/test_terminal_auth_trust_boundary.py",
            "migrations/versions/20260816_42a_terminal_v2.py",
            "migrations/versions/20260816_43a_terminal_superadmin_policy.py",
            "migrations/versions/20260816_44a_terminal_storage_isolation.py",
            "migrations/versions/20260816_45a_terminal_client_isolation.py",
        ):
            ast.parse(read(path), filename=path)

    def test_seq1200_agent_routes_are_registered(self) -> None:
        terminal = read("service1/routers/terminal.py")
        main = read("service1/main.py")
        self.assertIn('agent_router = APIRouter(prefix="/terminal-agent"', terminal)
        self.assertIn('@agent_router.websocket("/clients/{client_id}/ws")', terminal)
        self.assertIn('@agent_router.put("/clients/{client_id}/status")', terminal)
        self.assertIn('@agent_router.post("/clients/{client_id}/sessions/{session_id}/events")', terminal)
        self.assertIn("terminal_agent_router", main)
        self.assertIn("app.include_router(terminal_agent_router", main)

    def test_terminal_signing_trust_and_token_config_are_domain_isolated(self) -> None:
        source = read("service1/terminal_v2.py")
        render = (ROOT.parent / "render.yaml").read_text(encoding="utf-8")
        self.assertIn('os.getenv("CLIENTFLOW_TERMINAL_AUTH_KEY_B64")', source)
        self.assertIn('os.getenv("CLIENTFLOW_TERMINAL_AUTH_ISSUER")', source)
        self.assertIn('or "clientflow-terminal-auth"', source)
        self.assertIn('os.getenv("CLIENTFLOW_TERMINAL_TOKEN_ISSUER")', source)
        self.assertIn('or "planiq-display-api"', source)
        self.assertIn('os.getenv("CLIENTFLOW_TERMINAL_TOKEN_TTL_SECONDS", "600")', source)
        self.assertIn("_terminal_auth_signing_key()", source)
        self.assertIn("TERMINAL_AUTH_ISSUER", source)
        self.assertIn('os.getenv("CLIENTFLOW_ROOT_TERMINAL_KEY_B64")', source)
        self.assertIn("_root_signing_config()", source)
        self.assertNotIn("SECRET_KEY", source)
        self.assertNotIn("JWT_ISSUER", source)
        self.assertNotIn('CLIENTFLOW_DOMAIN_TOKEN_TTL_SECONDS', source)
        self.assertNotIn('LIVESTREAM_V2_TOKEN_ISSUER', source)
        self.assertIn("CLIENTFLOW_TERMINAL_AUTH_KEY_B64", render)
        self.assertIn("CLIENTFLOW_TERMINAL_AUTH_ISSUER", render)
        self.assertIn("CLIENTFLOW_TERMINAL_TOKEN_ISSUER", render)
        self.assertIn("CLIENTFLOW_TERMINAL_TOKEN_TTL_SECONDS", render)
        self.assertIn("CLIENTFLOW_ROOT_TERMINAL_KEY_B64", render)
        self.assertIn("CLIENTFLOW_ROOT_TERMINAL_KEY_ID", render)

    def test_terminal_domain_auth_uses_terminal_owned_credential_and_status_tables(self) -> None:
        source = read("service1/terminal_v2.py")
        router = read("service1/routers/terminal.py")
        terminal_models = read("service1/terminal_v2_models.py")
        self.assertIn("TerminalCredential", source)
        self.assertIn("TerminalAgentStatus", source)
        self.assertIn("TerminalCredential", router)
        self.assertNotIn("ClientDomainCredential", source)
        self.assertNotIn("ClientDomainStatus", source)
        self.assertNotIn("ClientDomainCredential", router)
        terminal_tree = ast.parse(terminal_models)
        terminal_table_names = {
            node.value.value
            for node in ast.walk(terminal_tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and target.id == "__tablename__"
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        }
        self.assertEqual(
            terminal_table_names,
            {
                "terminal_client",
                "terminal_credential",
                "terminal_agent_status",
                "terminal_session",
                "root_terminal_grant",
                "terminal_session_event",
            },
        )
        self.assertIn('foreign_key="terminal_credential.id"', terminal_models)
        self.assertNotIn('foreign_key="client_domain_credential.id"', terminal_models)
        self.assertIn("verify_password(client_secret, row.secret_hash)", source)
        self.assertIn('"domain": DOMAIN', source)
        self.assertNotIn("client_secret_hash", source)

    def test_terminal_client_id_preserves_existing_ids_without_sequence_default(self) -> None:
        models = read("service1/terminal_v2_models.py")
        migration = read("migrations/versions/20260816_45a_terminal_client_isolation.py")
        self.assertIn("Column(Integer, primary_key=True, autoincrement=False)", models)
        self.assertIn('sa.Column("id", sa.Integer(), nullable=False, autoincrement=False)', migration)

    def test_terminal_client_identity_is_terminal_owned_and_legacy_agent_fallback_is_removed(self) -> None:
        service = read("service1/terminal_v2.py")
        router = read("service1/routers/terminal.py")
        models = read("service1/terminal_v2_models.py")
        tickets = read("service1/routers/websocket_tickets.py")
        migration = read("migrations/versions/20260816_45a_terminal_client_isolation.py")
        contract = read("scripts/terminal_v2_schema_contract.py")

        self.assertIn('class TerminalClient(SQLModel, table=True):', models)
        self.assertIn('__tablename__ = "terminal_client"', models)
        self.assertIn('foreign_key="terminal_client.id"', models)
        self.assertNotIn('foreign_key="client.id"', models)
        self.assertIn('session.get(TerminalClient, client_id)', service)
        self.assertNotIn('session.get(Client, client_id)', service)
        self.assertNotIn('from .models import Client', service)
        self.assertNotIn('from ..models import Client, User', router)
        self.assertNotIn('verify_ws_token', router)
        self.assertNotIn('\nCLIENTS:', router)
        self.assertNotIn('@router.websocket("/client/{client_id}/ws")', router)
        self.assertNotIn('"legacy"', router)
        self.assertNotIn('TerminalClient', tickets)
        self.assertNotIn('TERMINAL_USER', tickets)
        self.assertNotIn('TERMINAL_ADMIN', tickets)
        self.assertIn('"terminal_client"', migration)
        self.assertIn('REFERENCES terminal_client(id)', contract)
        self.assertNotIn('FOREIGN KEY (client_id) REFERENCES client(id)', contract)

    def test_terminal_owns_dedicated_token_endpoint_and_livestream_router_does_not(self) -> None:
        terminal_auth = read("service1/routers/terminal_auth.py")
        livestream_router = read("service1/routers/livestream_v2.py")
        compat = read("service1/routers/client_auth_compat.py")
        main = read("service1/main.py")
        self.assertIn('@router.post("/terminal-auth/token")', terminal_auth)
        self.assertIn("issue_terminal_token_response", terminal_auth)
        self.assertNotIn('/client-auth/token', livestream_router)
        self.assertNotIn("issue_terminal_token_response", livestream_router)
        self.assertIn('@router.post("/client-auth/token")', compat)
        self.assertNotIn('if body.domain == "terminal":', compat)
        self.assertNotIn("issue_terminal_token_response", compat)
        self.assertNotIn("terminal_v2", compat)
        self.assertIn('if body.domain == "livestream":', compat)
        self.assertIn("terminal_auth_router", main)
        self.assertIn("client_auth_compat_router", main)
        self.assertFalse((ROOT / "service1/client_domain_auth_dispatch.py").exists())

    def test_terminal_browser_ticket_runtime_is_isolated_from_remote_desktop(self) -> None:
        router = read("service1/routers/terminal.py")
        terminal_ws_auth = read("service1/terminal_websocket_auth.py")
        shared_ws_auth = read("service1/websocket_auth.py")
        shared_tickets = read("service1/routers/websocket_tickets.py")
        frontend = (ROOT.parent / "frontend/src/api/api.js").read_text(encoding="utf-8")
        dialog = (ROOT.parent / "frontend/src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx").read_text(encoding="utf-8")
        render = (ROOT.parent / "render.yaml").read_text(encoding="utf-8")

        ticket_endpoint = router[
            router.index('@router.post("/browser-ticket"'):
            router.index('@router.websocket("/browser/{client_id}/ws")')
        ]
        self.assertIn('user: User = Depends(get_current_superadmin_user)', ticket_endpoint)
        self.assertIn('token: str = Depends(oauth2_scheme)', ticket_endpoint)
        self.assertIn('session: Session = Depends(get_session)', ticket_endpoint)
        self.assertIn('bucket="terminal-browser-ws-ticket"', ticket_endpoint)
        self.assertIn('require_active_browser_auth_session_binding(', ticket_endpoint)
        self.assertIn("issue_terminal_browser_ws_ticket", ticket_endpoint)
        self.assertIn("authenticate_terminal_browser_websocket_with_context", router)
        self.assertIn("_TERMINAL_BROWSER_WS_TICKETS", terminal_ws_auth)
        self.assertIn("_TERMINAL_TICKET_LOCK", terminal_ws_auth)
        self.assertIn('frozenset({"terminal_user", "terminal_admin"})', terminal_ws_auth)
        self.assertNotIn("terminal_user", shared_ws_auth)
        self.assertNotIn("terminal_admin", shared_ws_auth)
        self.assertNotIn("TerminalClient", shared_tickets)
        self.assertNotIn("TERMINAL_USER", shared_tickets)
        self.assertNotIn("TERMINAL_ADMIN", shared_tickets)
        self.assertIn('frozenset({"remote_desktop"})', shared_ws_auth)
        self.assertIn('buildApiUrl("/terminal/browser-ticket")', frontend)
        self.assertIn('new Set(["remote_desktop"])', frontend)
        self.assertIn("createTerminalBrowserWsTicket", dialog)
        self.assertNotIn("createBrowserWsTicket", dialog)
        self.assertIn("TERMINAL_BROWSER_WS_TICKET_TTL_SECONDS", render)
        self.assertIn("TERMINAL_BROWSER_WS_TICKET_MAX_PENDING", render)
        self.assertNotIn("verify_ws_token", terminal_ws_auth)
        self.assertNotIn("get_access_token_session_binding", terminal_ws_auth)
        self.assertNotIn('cookies.get("access_token")', terminal_ws_auth)
        self.assertNotIn("from ..websocket_auth import", router)
        self.assertIn("def extract_terminal_agent_ws_token", router)
        self.assertNotIn('websocket.cookies.get("access_token")', router)

    def test_user_admin_product_modes_map_to_standard_root_runtime(self) -> None:
        source = read("service1/terminal_v2.py")
        terminal = read("service1/routers/terminal.py")
        self.assertIn('privilege = "root" if mode == "admin" else "standard"', source)
        self.assertIn('"type": "session_start"', source)
        self.assertIn('"privilege_level": terminal_session.privilege_level', source)
        self.assertIn('VALID_TERMINAL_MODES = {"user", "admin"}', terminal)

    def test_admin_session_parent_is_flushed_before_root_grant(self) -> None:
        source = read("service1/routers/terminal.py")
        function = source[source.index("async def _start_v2_browser_session"):source.index("async def _stage_script_v2")]
        flush_pos = function.index("session.flush([terminal_session])")
        grant_pos = function.index("root_grant = issue_root_terminal_grant(")
        commit_pos = function.index("session.commit()")
        self.assertLess(flush_pos, grant_pos)
        self.assertLess(grant_pos, commit_pos)

    def test_root_grant_matches_seq1200_broker_contract(self) -> None:
        source = read("service1/terminal_v2.py")
        for required in (
            'ROOT_GRANT_AUDIENCE = "clientflow-root-terminal-broker"',
            'ROOT_GRANT_ISSUER = "clientflow-backend"',
            '"capability": "root_pty"',
            'f"root-terminal:{terminal_session.id}"',
            'headers={"kid": key_id}',
            '"credential_id": credential.id',
        ):
            self.assertIn(required, source)


    def test_both_terminal_modes_are_superadmin_only_at_backend_boundaries(self) -> None:
        router = read("service1/routers/terminal.py")
        service = read("service1/terminal_v2.py")
        self.assertIn("user: User = Depends(get_current_superadmin_user)", router)
        self.assertIn('if not getattr(user, "is_superadmin", False):', router)
        self.assertIn('detail="Kun superadministratorer må åbne Terminal"', service)
        self.assertIn('privilege = "root" if mode == "admin" else "standard"', service)
        self.assertIn('def _current_terminal_superadmin(browser: BrowserSession)', router)
        self.assertIn('getattr(current_user, "is_superadmin", False)', router)
        self.assertIn('browser.user_token_version', router)
        self.assertIn('TERMINAL_BROWSER_AUTH_RECHECK_SECONDS = 15.0', router)
        self.assertIn('done, _ = await asyncio.wait(', router)
        self.assertIn('_current_terminal_superadmin(browser)', router)

    def test_admin_terminal_has_session_bound_ten_minute_recent_step_up(self) -> None:
        auth = read("service1/auth.py")
        service = read("service1/terminal_v2.py")
        router = read("service1/routers/terminal.py")
        terminal_ws_auth = read("service1/terminal_websocket_auth.py")
        frontend = (ROOT.parent / "frontend/src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx").read_text(encoding="utf-8")
        api = (ROOT.parent / "frontend/src/api/api.js").read_text(encoding="utf-8")

        self.assertIn('CLIENTFLOW_TERMINAL_ADMIN_STEP_UP_SECONDS", "600"', service)
        self.assertIn("verify_password(raw, user.hashed_password)", service)
        self.assertIn('"session_binding": binding', service)
        self.assertIn("verify_admin_terminal_step_up_token", service)
        self.assertIn("step_up_verified_at=step_up_verified_at", service)
        self.assertIn("get_access_token_session_binding", auth)
        self.assertIn("require_active_browser_auth_session_binding", router)
        self.assertIn("auth_session_binding: Optional[str]", terminal_ws_auth)
        self.assertIn('msg, "step_up_token"', router)
        self.assertIn('msg, "password"', router)
        self.assertIn('"type": "admin_step_up"', router)
        self.assertIn("getAdminTerminalStepUpToken", frontend)
        self.assertIn("setAdminTerminalStepUp", frontend)
        self.assertIn('type="password"', frontend)
        self.assertIn("adminTerminalStepUpInMemory", api)
        self.assertNotIn("localStorage.setItem(\"admin", api)

    def test_admin_terminal_reason_is_not_required_or_collected(self) -> None:
        service = read("service1/terminal_v2.py")
        router = read("service1/routers/terminal.py")
        models = read("service1/terminal_v2_models.py")
        contract = read("scripts/terminal_v2_schema_contract.py")
        policy_migration = read("migrations/versions/20260816_43a_terminal_superadmin_policy.py")
        frontend = (ROOT.parent / "frontend/src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx").read_text(encoding="utf-8")
        self.assertNotIn("Admin-terminal kræver en begrundelse", service)
        self.assertNotIn('msg, "reason"', router)
        self.assertNotIn("ck_terminal_session_root_reason", models)
        self.assertNotIn('"ck_terminal_session_root_reason":', contract)
        self.assertIn('op.drop_constraint(', policy_migration)
        self.assertIn('"ck_terminal_session_root_reason"', policy_migration)
        self.assertNotIn("Begrundelse for Admin-terminal", frontend)
        self.assertNotIn("adminReason", frontend)

    def test_browser_and_agent_session_ids_are_separate_for_repeated_ptys(self) -> None:
        router = read("service1/routers/terminal.py")
        self.assertIn("agent_session_id: Optional[str] = None", router)
        self.assertIn("V2_SESSIONS: dict[str, BrowserSession]", router)
        self.assertIn("agent_session_id = str(uuid.uuid4())", router)
        self.assertIn("V2_SESSIONS[agent_session_id] = browser", router)
        self.assertIn("browser.agent_session_id = None", router)

    def test_late_agent_events_do_not_undo_revocation(self) -> None:
        service = read("service1/terminal_v2.py")
        self.assertIn('terminal_session.status not in {"revoked", "expired", "failed"}', service)
        self.assertIn('if terminal_session.status != "revoked":', service)

    def test_terminal_schema_preserves_reviewed_production_varchar_lengths(self) -> None:
        contract = read("scripts/terminal_v2_schema_contract.py")
        migration = read("migrations/versions/20260816_44a_terminal_storage_isolation.py")
        for snippet in (
            '"id": {"data_type": "character varying", "default": None, "length": 36',
            '"observed_state": {"data_type": "character varying", "default": "\'unknown\'::character varying", "length": 80',
            '"boot_id": {"data_type": "character varying", "default": None, "length": 128',
            '"privilege_level": {"data_type": "character varying", "default": "\'standard\'::character varying", "length": 20',
            '"status": {"data_type": "character varying", "default": "\'authorized\'::character varying", "length": 30',
            '"grant_hash": {"data_type": "character varying", "default": None, "length": 64',
            '"event_type": {"data_type": "character varying", "default": None, "length": 80',
        ):
            self.assertIn(snippet, contract)
        for snippet in ('sa.String(36)', 'sa.String(80)', 'sa.String(128)'):
            self.assertIn(snippet, migration)

    def test_storage_migration_moves_terminal_rows_out_of_shared_tables(self) -> None:
        migration = read("migrations/versions/20260816_44a_terminal_storage_isolation.py")
        contract = read("scripts/terminal_v2_schema_contract.py")
        self.assertIn('"terminal_credential"', migration)
        self.assertIn('"terminal_agent_status"', migration)
        self.assertIn("FROM client_domain_credential", migration)
        self.assertIn("WHERE domain = 'terminal'", migration)
        self.assertIn("DELETE FROM client_domain_status WHERE domain = 'terminal'", migration)
        self.assertIn("DELETE FROM client_domain_credential WHERE domain = 'terminal'", migration)
        self.assertIn('REFERENCES terminal_credential(id)', contract)
        self.assertNotIn('REFERENCES client_domain_credential(id)', contract)

    def test_terminal_schema_is_adopted_at_new_head(self) -> None:
        base_migration = read("migrations/versions/20260816_42a_terminal_v2.py")
        policy_migration = read("migrations/versions/20260816_43a_terminal_superadmin_policy.py")
        isolation_migration = read("migrations/versions/20260816_44a_terminal_storage_isolation.py")
        client_isolation_migration = read("migrations/versions/20260816_45a_terminal_client_isolation.py")
        contract = read("scripts/display_schema_contract.py")
        runner = read("scripts/run_migrations.py")
        self.assertIn('down_revision = "20260814_41a_livestream_v2"', base_migration)
        self.assertIn('down_revision = "20260816_42a_terminal_v2"', policy_migration)
        self.assertIn('down_revision = "20260816_43a_terminal_policy"', isolation_migration)
        self.assertIn('down_revision = "20260816_44a_terminal_store"', client_isolation_migration)
        self.assertEqual(contract.rsplit('EXPECTED_HEAD_REVISION = ', 1)[1].splitlines()[0], '"20260823_53b_system_authority"')
        self.assertIn('REVIEWED_BASELINE_ADOPTION_HEAD = "20260823_53b_system_authority"', runner)
        self.assertIn("HEAD_LEGACY_PRESERVED_TABLES", runner)
        self.assertIn("_without_terminal_v2_schema", runner)


    def test_browser_close_is_idempotent_across_explicit_close_and_websocket_finally(self) -> None:
        router = read("service1/routers/terminal.py")
        self.assertIn("agent_close_sent: bool = False", router)
        self.assertIn("and not browser.agent_close_sent", router)
        self.assertIn("browser.agent_close_sent = await _send_to_domain_agent", router)
        self.assertIn("if domain_conn and not removed_browser.agent_close_sent", router)



if __name__ == "__main__":
    unittest.main()
