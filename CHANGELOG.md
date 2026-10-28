# Changelog

What changed for people who use omniverse-mcp, newest first. A change users notice adds its line under Unreleased in
the same PR. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Security

- **The bridge answers only the MCP server that holds its token.** Before this, any program on the machine, and any
  web page open in a browser, could send `/execute` to the extension and run Python inside the Kit app. The extension
  now writes a new random token to a file only your user can read, every request must carry it, and requests from web
  pages are refused.

### Breaking changes

- **Update the MCP server and the Kit extension together.** A new server refuses an old extension, and an old server
  gets 401 from a new one. `git pull` in your checkout updates both; then restart Kit and your MCP client.
- **A remote Kit app needs the token by hand:** set the extension's `token` setting and the server's
  `OMNIVERSE_MCP_TOKEN` to the same value.
