"""Tool implementations.

Read-only tools:
- inventory: Product and stock data
- sales: Sales velocity and history
- vendors: Offers and performance metrics
- policy: Budget and procurement policy

Write-only tools (deterministic nodes only):
- execution: Revalidation and purchase request creation
- langchain_tools: Pydantic-validated StructuredTool wrappers
- workflow: Proposal recommendation and human-review helpers
"""
