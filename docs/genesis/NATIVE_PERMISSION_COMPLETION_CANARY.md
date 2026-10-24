# Native enrollment permission canary

This static document is the complete change for a one-time, owner-authorized
GitHub-native enrollment permission test. It changes no application behavior,
workflow, credential, policy, or branch protection.

The test uses the existing restricted Actions token and an exact-head condition.
GitHub must continue enforcing all existing protected merge requirements.
A successful enrollment is not a successful merge or permission to expand
production autonomy. An uncertain request must not be retried.
