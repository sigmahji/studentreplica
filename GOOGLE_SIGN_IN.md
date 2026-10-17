# Google Sign-In

StudentReplica uses Streamlit's native OIDC flow and Authlib, not a custom OAuth
callback. Username/password accounts and demo sessions remain available. A
disabled Google button means this deployment's setup is incomplete; it does not
mean the Groq API is unavailable.

## Enable Google Login

1. In [Google Auth Platform](https://console.cloud.google.com/auth/overview),
   choose your project and configure the consent screen for StudentReplica.
   Configure the appropriate audience and add your test accounts while testing.
2. Create an OAuth client of type **Web application**. Add exact authorized
   redirect URIs for each deployment:

   ```text
   http://localhost:8501/oauth2callback
   https://YOUR-APP.streamlit.app/oauth2callback
   ```

   Match the port and hostname you actually use. Docker's example uses local
   port 8502 instead. Google OAuth credentials are not Google API keys or Groq keys.
3. Generate a private cookie-signing secret locally:

   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

4. Add this configuration to the ignored `.streamlit/secrets.toml` for local use,
   or **App settings > Secrets** on Streamlit Cloud. Replace all placeholders.
   Keep existing root-level AI and database entries above these tables:

   ```toml
   [auth]
   redirect_uri = "http://localhost:8501/oauth2callback"
   cookie_secret = "replace-with-your-generated-cookie-secret"

   [auth.google]
   client_id = "replace-with-google-client-id.apps.googleusercontent.com"
   client_secret = "replace-with-google-client-secret"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```

   Cloud must use its exact HTTPS callback URL in both Secrets and Google. Do
   not put these values under `[ai]`, expose tokens, or commit real credentials.
   Google authentication uses Streamlit Secrets, not `.env` AI settings.
5. Install updated requirements, restart/reboot the app, then choose
   **Continue with Google**. Google may restrict access to test users until you
   publish your configured consent screen. For Docker, bind-mount the private
   secrets file read-only at `/app/.streamlit/secrets.toml` at runtime; it is
   intentionally excluded from the image. Do not bake it into the Dockerfile.

Configuration and callback behavior follow the
[official Streamlit Google tutorial](https://docs.streamlit.io/develop/tutorials/authentication/google).

## Account And Data Safety

- Streamlit/Authlib verifies the OIDC response, including signature, audience,
  state and nonce. The app consumes only server-side `st.user`, never a user ID
  supplied in a query parameter or form.
- Each stable Google subject maps to one StudentReplica UUID through
  `external_identities`. Only its SHA-256 digest is stored, not the raw subject,
  Google email, profile picture, ID token or access token. Existing repository
  operations continue filtering all student records by that UUID.
- Google subjects, not names or email addresses, determine identity, following
  [Google's identity guidance](https://developers.google.com/identity/openid-connect/openid-connect).
- Existing username/password accounts are **not automatically linked or merged**.
  Continue using your existing username login to reach its saved data. First
  Google sign-in creates a separate account and starts the existing onboarding
  tour. Moving or linking existing data requires a separately authenticated,
  explicit workflow; no such linking is performed here.
- Google-only accounts cannot use password login. No Google password is requested
  or stored. The provider display name is limited to the existing 120 characters.
- Expired/unverified claims stop access before loading student records. Switching
  identities clears prior form state. Logout clears app identity and the native
  identity cookie, without signing the user out of Google itself.
- Native logout does not terminate other already-open Streamlit sessions. Close
  all tabs on shared computers. See
  [Streamlit's session behavior](https://docs.streamlit.io/develop/concepts/connections/authentication).

## Storage Upgrade And Checks

Startup adds one new table without rewriting existing accounts or twins. The
table has an account foreign key and unique identity constraints. PostgreSQL
also enables backend-only row-level security through the existing initialization.
Back up existing records before deploying changes. Google sign-in does not make
local SQLite durable on Streamlit Cloud; use the configured PostgreSQL backend.

Run `python -m pytest -q`. Synthetic tests cover repeat sign-ins, different
students with the same email/name, full pipeline and prompt isolation,
concurrent first login, transaction rollback, legacy schema upgrade, expired
claims, native login/logout calls and form-state cleanup. They never call Google.

For live acceptance testing after configuration:

1. Sign in with Google account A, save a profile and sign out.
2. Sign in with a different Google account B; verify A's data is absent.
3. Sign in again as A and verify its profile and progress are restored.
4. Reboot the app and repeat; confirm existing username/password login also works.

Real Google consent and callback success require your own configured client and
browser login; synthetic tests cannot establish that external setup is correct.
