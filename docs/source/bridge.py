"""Local browser adapter; game decisions remain in the existing demo engine."""
import json

from ui.ekona_demo.model import DemoSession

class BrowserDemoSession(DemoSession):
    def _perform(self, action, payload):
        if self.stage == "intro" and action == "start_mini":
            # Missing values belong to existing six-believer command histories.
            starting_believers = payload.get("starting_believers", 6)
            if type(starting_believers) is not int or starting_believers not in {6, 12}:
                raise ValueError("Invalid mini-match starting flock.")
            self.state.players["p1"].meeples = starting_believers
        super()._perform(action, payload)


session = BrowserDemoSession()


def browser_view():
    return session.view() | {"csrf": "browser-local"}


def browser_initialize(encoded):
    global session
    payload = json.loads(encoded)
    commands = payload.get("commands", [])
    if not isinstance(commands, list) or len(commands) > 2000:
        raise ValueError("Invalid local preview history.")
    session = BrowserDemoSession()
    for command in commands:
        browser_action(json.dumps(command))
    if not commands and payload.get("mini"):
        browser_action(json.dumps({"action": "start_mini", "revision": 0,
                                   "starting_believers": 6}))
    return json.dumps(browser_view(), ensure_ascii=False)


def browser_action(encoded):
    payload = json.loads(encoded)
    if not isinstance(payload, dict) or type(payload.get("revision")) is not int:
        raise ValueError("Invalid local command.")
    if payload["revision"] != session.revision:
        raise ValueError("The local game revision has changed.")
    session.perform(payload["action"], payload)
    return json.dumps(browser_view(), ensure_ascii=False)
