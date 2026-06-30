"""MCP protocol handler."""
from mcp.server.fastmcp import FastMCP

from app.mcp import tools

mcp = FastMCP("openIndu-backend")

mcp.tool()(tools.search_plc_manual)
mcp.tool()(tools.search_hardware_manual)
mcp.tool()(tools.search_driver_manual)
mcp.tool()(tools.search_hmi_manual)
mcp.tool()(tools.search_robot_manual)
mcp.tool()(tools.search_software_manual)
mcp.tool()(tools.search_best_practice)
mcp.tool()(tools.search_electrical_standard)
mcp.tool()(tools.get_brand_mapping)
mcp.tool()(tools.suggest_plc_model)
mcp.tool()(tools.compare_plc_specs)
mcp.tool()(tools.list_available_documents)
mcp.tool()(tools.list_available_software)
