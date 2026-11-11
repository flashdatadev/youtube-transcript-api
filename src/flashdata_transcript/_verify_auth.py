"""Fresh-process verification of the persisted owner key; never accepts a key as an argument."""

import sys

from .auth import AuthManager, _connection, _key, _saved


def main() -> int:
    if len(sys.argv) != 4:
        return 1
    try:
        with AuthManager(sys.argv[1]) as manager:
            state = manager.store.read()
            if state is None:
                return 1
            _saved(state)
            connection = _connection(state["connection"], sys.argv[2])
            if connection["ownership"] != "owned" or connection["generation"] != int(sys.argv[3]):
                return 1
            result = manager._request("GET", f"/{connection['id']}/identity", _key(state))
            verified = _connection(result.get("connection"), connection["id"])
            if (
                verified["ownership"] != "owned"
                or verified["generation"] != connection["generation"]
            ):
                return 1
        print("verified")
        return 0
    except Exception:
        # Parent reports a safe recovery message, never a traceback with credential locals.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
