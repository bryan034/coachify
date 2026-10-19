# API contracts

One empty OpenAPI document per backend service. All `paths` objects are deliberately empty because no HTTP endpoint has been implemented. Review public resource ownership and private service identity before defining operations.

The public server prefix is `/api/v1`. Internal `/internal/v1` endpoints will be designed separately and blocked at the public gateway.
