# Security

The Kit extension runs any Python the MCP server sends it, inside your Kit app and as your user. The bridge token is
what stops anyone else from doing the same, so a way around it is serious.

## Reporting

Report it privately through a
[security advisory](https://github.com/serionist/omniverse-mcp/security/advisories/new), never in an issue, a pull
request or a discussion: anyone can read those. Say what an attacker can do and what they need first, how to reproduce
it, and which version or commit you tested, on which Kit app and operating system. Leave your own bridge token out.
You'll get an answer within a week.

## What counts

- Reaching `/execute`, or any other bridge route, without the token, or from a web page open in a browser.
- Reading another user's token file, `bridge-<port>.token` ([where it lives](docs/ARCHITECTURE.md#the-bridge-token)).
- Getting past the `Origin` or `Host` checks: a request a browser sends that the bridge answers, or DNS rebinding
  against a bridge bound to loopback.
- A tool that writes a file outside what its caller asked for: outside the output folder, or outside the path it was
  given, through a path in its arguments or a name in the scene.
- A secret written where it shouldn't be: the token, or any other key or password, in Kit's log, the server's log, or
  a file in the output folder.

What does not count:

- `execute_script` running Python inside Kit, or `manage_extensions` turning an extension on: that is what they are
  for.
- Someone who already holds the token, or already runs code as your user, running code in Kit. The token is the
  boundary.
- A bridge you bound off loopback, with the extension's `host` setting, being reachable from that network. The token
  still guards it, and the extension warns at startup.

## Supported versions

| Version | Fixes |
|---|---|
| The latest release | Every fix |
| Older releases | None before `1.0`: update to the latest |

Until `1.0`, only the latest release gets fixes.
