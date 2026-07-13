# Non-secret executor fixture for the init/doctor acceptance TaskCard.
# The live scoped value is inherited by the trusted runner; this file only
# asserts its presence and never copies or prints it.
export AWF_CODER_TOKEN="${AWF_CODER_TOKEN:?AWF_CODER_TOKEN is required}"
