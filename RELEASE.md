
# Guidelines for Releases

## Code Ownership and Automated Release Management

Releases within our project are exclusively overseen by designated code owners, as outlined in the [/ .github / CODEOWNERS](/.github/CODEOWNERS) file. Our release process is automated using the Release Please GitHub action, which is configured in [/ .github / workflows / release-please.yml](/.github/workflows/release-please.yml).

## Workflow Overview

1. **Initial Release**:
    - The Release Please GitHub action generates a pull request titled `chore(main): release 1.0.0`, initiating version 1.0.0.
    - This pull request requires approval from the designated code owners.

2. **Subsequent Releases**:
    - When changes are merged into the main branch, the Release Please GitHub action creates or updates an existing pull request titled `chore(main): release X.Y.Z`, where X.Y.Z is the version number derived from the commit history.

3. **Forcing a Specific Release Version**:
    - To manually set the next release version, create an empty commit on a new branch and merge it manually. Use the following command to create the empty commit:

    ```sh
    git commit --allow-empty -m "chore: release 62.1.0" -m "Release-As: 62.1.0"
    ```
    - Then, create a pull request from this branch and merge it manually.

For comprehensive information, please consult the [Release Please documentation](https://github.com/googleapis/release-please).
