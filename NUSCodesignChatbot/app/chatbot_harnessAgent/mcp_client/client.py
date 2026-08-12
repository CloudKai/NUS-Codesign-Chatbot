import os
import logging
from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient

logger = logging.getLogger(__name__)

from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

def get_gateway_course_materials_4cymlvixrt_mcp_client() -> MCPClient | None:
    """Returns an MCP Client connected to the gateway-course-materials-4cymlvixrt gateway."""
    url = os.environ.get("GATEWAY_GATEWAY_GATEWAY_COURSE_MATERIALS_4CYMLVIXRT_URL")
    if not url:
        logger.warning("GATEWAY_GATEWAY_GATEWAY_COURSE_MATERIALS_4CYMLVIXRT_URL not set — gateway-course-materials-4cymlvixrt gateway tools unavailable")
        return None
    return MCPClient(lambda: aws_iam_streamablehttp_client(url, aws_service="bedrock-agentcore", aws_region=os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION"))), prefix="gateway_course_materials_4cymlvixrt")

def get_all_gateway_mcp_clients() -> list[MCPClient]:
    """Returns MCP clients for all configured gateways."""
    clients = []
    client = get_gateway_course_materials_4cymlvixrt_mcp_client()
    if client:
        clients.append(client)
    return clients
