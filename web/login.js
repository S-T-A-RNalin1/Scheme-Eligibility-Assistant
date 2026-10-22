// Login page: separate Citizen and Admin sign-in (loads after common.js).
const params = new URLSearchParams(location.search);
let role = params.get("role") === "admin" ? "admin" : "citizen";
let mode = "login";

function safeNext(forRole) {
  const n = params.get("next") || "";
  if (!n.startsWith("/") || n.startsWith("//")) return "/";  // only same-site redirects
  if (forRole !== "admin" && n.startsWith("/admin")) return "/";  // citizens never bounce back to the dashboard
  return n;
}

function render() {
  document.querySelectorAll(".role-tab").forEach((b) => {
    const on = b.dataset.role === role;
    b.classList.toggle("active", on); b.setAttribute("aria-selected", on);
  });
  if (role === "admin") mode = "login";
  document.querySelectorAll(".mode").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $("#mode-switch").classList.toggle("hidden", role === "admin");
  $("#name-row").classList.toggle("hidden", mode !== "register");
  $("#admin-note").hidden = role !== "admin";
  $("#role-note").textContent = role === "admin"
    ? "For officers: handle grievances and see coverage analytics."
    : "Check eligibility, save your profile and file grievances.";
  $("#lg-pass").autocomplete = mode === "register" ? "new-password" : "current-password";
  $("#lg-submit").textContent = role === "admin" ? "Login as admin" : mode === "register" ? "Create citizen account" : "Login as citizen";
  document.body.classList.toggle("admin-mode", role === "admin");
}

document.querySelectorAll(".role-tab").forEach((b) => b.onclick = () => { role = b.dataset.role; render(); });
document.querySelectorAll(".mode").forEach((b) => b.onclick = () => { mode = b.dataset.mode; render(); });

$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  const email = $("#lg-email").value.trim(), password = $("#lg-pass").value;
  if (!email || !password) return toast("Enter your email and password", true);
  if (mode === "register" && password.length < 8) return toast("Password must be at least 8 characters", true);
  const btn = $("#lg-submit"); btn.disabled = true;
  try {
    const r = mode === "register"
      ? await getJSON("/auth/register", { method: "POST", body: { email, password, name: $("#lg-name").value.trim() } })
      : await getJSON("/auth/login", { method: "POST", body: { email, password, as_role: role } });
    saveSession(r.token, r.user);
    toast("Welcome " + (r.user.name || r.user.email));
    location.href = r.user.role === "admin" ? "/admin" : safeNext(r.user.role);
  } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
};

// Already signed in: admins go to the dashboard; a citizen who asked for the admin area stays here
// with a note (sending them back to /admin would loop), otherwise they return to where they were.
if (me && isAdmin()) location.replace("/admin");
else if (me && role === "admin") { render(); toast(`You're signed in as a citizen (${me.email}). Sign in with an admin account to open the dashboard.`, true); }
else if (me) location.replace(safeNext(me.role));
else render();
