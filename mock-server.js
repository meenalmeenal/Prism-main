// mock-server.js — Comprehensive mock server for Prism test automation
const express = require('express');
const app = express();
const port = 3000;

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ─── In-memory state ───────────────────────────────────────────────────────
const VALID_USERS = {
  'testuser@example.com': { password: 'password123', name: 'Test User', id: 1 },
  'admin@example.com':    { password: 'Admin@1234', name: 'Admin User', id: 2 },
};

const registeredUsers = { ...VALID_USERS }; // grows as new users register

const loginAttempts = {};   // email → { count, lockedUntil }
const sessions = {};        // token → { email, name }

const LOCKOUT_ATTEMPTS = 5;
const LOCKOUT_DURATION_MS = 5 * 60 * 1000; // 5 minutes

// SQL injection patterns
const SQL_INJECTION_RE = /('|--|;|\/\*|\*\/|xp_|UNION|SELECT|INSERT|DELETE|UPDATE|DROP|OR\s+['"]?1['"]?\s*=\s*['"]?1)/i;

// ─── Helper: shared CSS ────────────────────────────────────────────────────
const sharedCSS = `
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; background: #f4f4f4; display: flex; justify-content: center; align-items: flex-start; min-height: 100vh; padding: 40px 16px; }
  .card { background: #fff; padding: 32px; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); width: 100%; max-width: 420px; }
  h1 { margin-bottom: 24px; font-size: 1.5rem; color: #333; }
  .field { margin-bottom: 16px; }
  label { display: block; margin-bottom: 4px; font-size: 0.9rem; color: #555; }
  input[type=text], input[type=email], input[type=password] { width: 100%; padding: 10px 12px; border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; }
  input:focus { outline: none; border-color: #4a90e2; box-shadow: 0 0 0 2px rgba(74,144,226,0.2); }
  button { width: 100%; padding: 12px; background: #4a90e2; color: #fff; border: none; border-radius: 4px; font-size: 1rem; cursor: pointer; margin-top: 8px; }
  button:hover { background: #357abd; }
  button:disabled { background: #aaa; cursor: not-allowed; }
  .error-msg  { color: #e00; font-size: 0.85rem; margin-top: 4px; display: none; }
  .success-msg { color: #0a0; font-size: 0.85rem; margin-top: 12px; display: none; }
  .global-error { color: #fff; background: #e00; padding: 10px 14px; border-radius: 4px; margin-bottom: 16px; display: none; font-size: 0.9rem; }
  .global-success { color: #fff; background: #0a0; padding: 10px 14px; border-radius: 4px; margin-bottom: 16px; display: none; font-size: 0.9rem; }
  .links { margin-top: 16px; font-size: 0.9rem; }
  .links a { color: #4a90e2; text-decoration: none; }
  .links a:hover { text-decoration: underline; }
  @media (max-width: 480px) { .card { padding: 20px; } h1 { font-size: 1.2rem; } }
`;

// ─── Helper: generate session token ───────────────────────────────────────
function generateToken() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// ─── Helper: check lockout ─────────────────────────────────────────────────
function checkLockout(email) {
  const rec = loginAttempts[email];
  if (!rec) return null;
  if (rec.lockedUntil && Date.now() < rec.lockedUntil) {
    const secsLeft = Math.ceil((rec.lockedUntil - Date.now()) / 1000);
    return `Account temporarily locked. Try again in ${secsLeft} seconds.`;
  }
  return null;
}

function recordFailedAttempt(email) {
  if (!loginAttempts[email]) loginAttempts[email] = { count: 0, lockedUntil: null };
  loginAttempts[email].count += 1;
  if (loginAttempts[email].count >= LOCKOUT_ATTEMPTS) {
    loginAttempts[email].lockedUntil = Date.now() + LOCKOUT_DURATION_MS;
    loginAttempts[email].count = 0;
  }
}

function clearAttempts(email) {
  delete loginAttempts[email];
}

// ─── API: Login ────────────────────────────────────────────────────────────
app.post('/api/login', (req, res) => {
  const { email, password, username } = req.body;
  const userEmail = (email || username || '').trim();
  const userPass  = (password || '').trim();

  if (!userEmail) return res.status(400).json({ success: false, message: 'Email is required' });
  if (!userPass)  return res.status(400).json({ success: false, message: 'Password is required' });

  // SQL injection check
  if (SQL_INJECTION_RE.test(userEmail) || SQL_INJECTION_RE.test(userPass)) {
    return res.status(400).json({ success: false, message: 'Invalid input detected. Access denied.' });
  }

  // Email format check
  if (!userEmail.includes('@') || userEmail.split('@')[1]?.trim() === '') {
    return res.status(400).json({ success: false, message: 'Invalid email format' });
  }

  // Lockout check
  const lockMsg = checkLockout(userEmail);
  if (lockMsg) return res.status(429).json({ success: false, message: lockMsg });

  // Credential check
  const user = registeredUsers[userEmail.toLowerCase()];
  if (!user || user.password !== userPass) {
    recordFailedAttempt(userEmail);
    const rec = loginAttempts[userEmail];
    const remaining = rec ? Math.max(0, LOCKOUT_ATTEMPTS - rec.count) : LOCKOUT_ATTEMPTS;
    const msg = remaining <= 1
      ? `Incorrect credentials. 1 attempt remaining before lockout.`
      : `Incorrect email or password. ${remaining} attempts remaining.`;
    return res.status(401).json({ success: false, message: msg });
  }

  // Success
  clearAttempts(userEmail);
  const token = generateToken();
  sessions[token] = { email: userEmail, name: user.name };
  res.status(200).json({ success: true, message: 'Login successful!', token, name: user.name, redirect: '/dashboard' });
});

// ─── API: Register ─────────────────────────────────────────────────────────
app.post('/api/register', (req, res) => {
  const { name, email, password, confirmPassword } = req.body;
  const errors = {};

  if (!name?.trim())     errors.name     = 'Name is required';
  if (!email?.trim())    errors.email    = 'Email is required';
  if (!password?.trim()) errors.password = 'Password is required';

  if (Object.keys(errors).length) {
    return res.status(400).json({ success: false, message: 'Please fill in all required fields', errors });
  }

  // Email format
  if (!email.includes('@') || email.split('@')[1]?.trim() === '') {
    return res.status(400).json({ success: false, message: 'Invalid email format. Must contain @ and a domain.', errors: { email: 'Invalid email format' } });
  }

  // SQL injection
  if (SQL_INJECTION_RE.test(email) || SQL_INJECTION_RE.test(name)) {
    return res.status(400).json({ success: false, message: 'Invalid input detected.' });
  }

  // Duplicate email
  if (registeredUsers[email.toLowerCase()]) {
    return res.status(409).json({ success: false, message: 'This email is already registered. Please use a different email.', errors: { email: 'Email already registered' } });
  }

  // Password strength
  if (password.length < 8) {
    return res.status(400).json({ success: false, message: 'Password must be at least 8 characters long.', errors: { password: 'Password must be at least 8 characters' } });
  }

  // Password confirmation
  if (confirmPassword && confirmPassword !== password) {
    return res.status(400).json({ success: false, message: 'Passwords do not match.', errors: { confirmPassword: 'Passwords do not match' } });
  }

  // Max email length
  if (email.length > 254) {
    return res.status(400).json({ success: false, message: 'Email address is too long.', errors: { email: 'Email too long' } });
  }

  // Register
  registeredUsers[email.toLowerCase()] = { password, name: name.trim(), id: Object.keys(registeredUsers).length + 1 };
  return res.status(201).json({ success: true, message: 'Registration successful! A confirmation email has been sent.' });
});

// ─── API: Logout ───────────────────────────────────────────────────────────
app.post('/api/logout', (req, res) => {
  const token = req.headers.authorization?.replace('Bearer ', '');
  if (token) delete sessions[token];
  res.status(200).json({ success: true, message: 'Logged out successfully', redirect: '/' });
});

// ─── API: Protected ────────────────────────────────────────────────────────
app.get('/api/protected', (req, res) => {
  const token = req.headers.authorization?.replace('Bearer ', '');
  if (!token || !sessions[token]) {
    return res.status(401).json({ success: false, message: 'Unauthorized. Please log in.' });
  }
  const user = sessions[token];
  res.status(200).json({ success: true, data: 'Protected dashboard data', user: user.name });
});

// ─── API: Reset Password ───────────────────────────────────────────────────
app.post('/api/reset-password', (req, res) => {
  const { email } = req.body;
  if (!email) return res.status(400).json({ success: false, message: 'Email is required' });
  if (!email.includes('@')) return res.status(400).json({ success: false, message: 'Invalid email format' });
  res.status(200).json({ success: true, message: `Password reset link sent to ${email}` });
});

app.post('/api/reset-confirm', (req, res) => {
  const { password, token } = req.body;
  if (!password || !token) return res.status(400).json({ success: false, message: 'Missing fields' });
  if (password.length < 8) return res.status(400).json({ success: false, message: 'Password must be at least 8 characters' });
  res.status(200).json({ success: true, message: 'Password reset successfully' });
});

// ─── Page: Login (/) ───────────────────────────────────────────────────────
app.get('/', (req, res) => {
  res.send(`<!DOCTYPE html><html lang="en"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Login - Test Application</title>
    <style>${sharedCSS}</style>
  </head><body><div class="card">
    <h1>Login</h1>
    <div id="global-error" class="global-error" role="alert"></div>
    <div id="global-success" class="global-success"></div>
    <div class="field">
      <label for="email">Email</label>
      <input type="email" id="email" aria-label="Email address" placeholder="you@example.com">
      <div class="error-msg" id="email-error"></div>
    </div>
    <div class="field">
      <label for="password">Password</label>
      <input type="password" id="password" aria-label="Password" placeholder="Password">
      <div class="error-msg" id="password-error"></div>
    </div>
    <div class="field">
      <label><input type="checkbox" id="remember-me"> Remember me</label>
    </div>
    <button id="login-btn" aria-label="Submit">Login</button>
    <div class="links">
      <a id="forgot-password-link" href="/reset-password">Forgot Password?</a> &nbsp;|&nbsp;
      <a id="register-link" href="/register">Don't have an account? Register</a>
    </div>
    <div id="protected-content" style="display:none;">
      <h2>Protected Content</h2><p>This is only visible after login.</p>
    </div>
  </div>
  <script>
    function showError(id, msg) {
      const el = document.getElementById(id);
      el.textContent = msg; el.style.display = msg ? 'block' : 'none';
    }
    function showGlobal(type, msg) {
      const e = document.getElementById('global-error');
      const s = document.getElementById('global-success');
      e.style.display = 'none'; s.style.display = 'none';
      if (type === 'error') { e.textContent = msg; e.style.display = 'block'; }
      if (type === 'success') { s.textContent = msg; s.style.display = 'block'; }
    }
    document.getElementById('login-btn').addEventListener('click', async () => {
      const email = document.getElementById('email').value.trim();
      const password = document.getElementById('password').value;
      showError('email-error', ''); showError('password-error', ''); showGlobal('', '');
      let valid = true;
      if (!email) { showError('email-error', 'Email is required'); valid = false; }
      if (!password) { showError('password-error', 'Password is required'); valid = false; }
      if (!valid) return;
      try {
        const res = await fetch('/api/login', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (data.success) {
          sessionStorage.setItem('token', data.token);
          sessionStorage.setItem('userName', data.name);
          showGlobal('success', data.message || 'Login successful!');
          setTimeout(() => { window.location.href = '/dashboard'; }, 800);
        } else {
          showGlobal('error', data.message);
        }
      } catch (err) { showGlobal('error', 'Login error: ' + err.message); }
    });
  </script></body></html>`);
});

// ─── Page: Dashboard ───────────────────────────────────────────────────────
app.get('/dashboard', (req, res) => {
  res.send(`<!DOCTYPE html><html lang="en"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Dashboard - Test Application</title>
    <style>${sharedCSS}
      .dashboard { max-width: 600px; width: 100%; }
      .topbar { display:flex; justify-content:space-between; align-items:center; background:#4a90e2; color:#fff; padding:12px 24px; border-radius:8px; margin-bottom:24px; }
      .topbar h2 { font-size:1.1rem; }
      #logout-btn { background:#e00; padding:8px 16px; border-radius:4px; cursor:pointer; border:none; color:#fff; font-size:0.9rem; }
    </style>
  </head><body><div class="dashboard">
    <div class="topbar">
      <h2 id="welcome-msg">Welcome!</h2>
      <button id="logout-btn">Logout</button>
    </div>
    <div class="card">
      <h1>Dashboard</h1>
      <p id="protected-content">You are now logged in. This is your dashboard.</p>
      <p id="user-info" style="margin-top:12px; color:#555;"></p>
    </div>
  </div>
  <script>
    const token = sessionStorage.getItem('token');
    const name  = sessionStorage.getItem('userName') || 'User';
    if (!token) { window.location.replace('/'); }
    document.getElementById('welcome-msg').textContent = 'Welcome, ' + name + '!';
    document.getElementById('user-info').textContent = 'Session active. Token: ' + token?.slice(0,8) + '...';
    history.pushState(null, '', window.location.href);
    window.addEventListener('popstate', () => { history.pushState(null, '', window.location.href); });
    document.getElementById('logout-btn').addEventListener('click', async () => {
      await fetch('/api/logout', { method: 'POST', headers: { 'Authorization': 'Bearer ' + token } });
      sessionStorage.clear();
      window.location.replace('/');
    });
  </script></body></html>`);
});

// ─── Page: Register ────────────────────────────────────────────────────────
app.get('/register', (req, res) => {
  res.send(`<!DOCTYPE html><html lang="en"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Register - Test Application</title>
    <style>${sharedCSS}</style>
  </head><body><div class="card">
    <h1>Create an Account</h1>
    <div id="global-error" class="global-error" role="alert"></div>
    <div id="global-success" class="global-success"></div>
    <div class="field">
      <label for="name">Full Name</label>
      <input type="text" id="name" aria-label="Full name" placeholder="Your name">
      <div class="error-msg" id="name-error"></div>
    </div>
    <div class="field">
      <label for="email">Email</label>
      <input type="email" id="email" aria-label="Email address" placeholder="you@example.com">
      <div class="error-msg" id="email-error"></div>
    </div>
    <div class="field">
      <label for="password">Password</label>
      <input type="password" id="password" aria-label="Password" placeholder="Min 8 characters">
      <div class="error-msg" id="password-error"></div>
    </div>
    <div class="field">
      <label for="confirm-password">Confirm Password</label>
      <input type="password" id="confirm-password" aria-label="Confirm password" placeholder="Re-enter password">
      <div class="error-msg" id="confirm-error"></div>
    </div>
    <button id="register-btn">Register</button>
    <div class="links"><a href="/">Already have an account? Login</a></div>
  </div>
  <script>
    function showError(id, msg) {
      const el = document.getElementById(id);
      el.textContent = msg; el.style.display = msg ? 'block' : 'none';
    }
    function showGlobal(type, msg) {
      const e = document.getElementById('global-error');
      const s = document.getElementById('global-success');
      e.style.display = 'none'; s.style.display = 'none';
      if (type === 'error') { e.textContent = msg; e.style.display = 'block'; }
      if (type === 'success') { s.textContent = msg; s.style.display = 'block'; }
    }
    document.getElementById('register-btn').addEventListener('click', async () => {
      const name = document.getElementById('name').value.trim();
      const email = document.getElementById('email').value.trim();
      const password = document.getElementById('password').value;
      const confirm = document.getElementById('confirm-password').value;
      ['name-error','email-error','password-error','confirm-error'].forEach(id => showError(id,''));
      showGlobal('','');
      let valid = true;
      if (!name)    { showError('name-error', 'Name is required'); valid = false; }
      if (!email)   { showError('email-error', 'Email is required'); valid = false; }
      if (!password){ showError('password-error', 'Password is required'); valid = false; }
      if (password && password.length < 8) { showError('password-error', 'Password must be at least 8 characters'); valid = false; }
      if (password && confirm && password !== confirm) { showError('confirm-error', 'Passwords do not match'); valid = false; }
      if (!valid) return;
      try {
        const res = await fetch('/api/register', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, email, password, confirmPassword: confirm })
        });
        const data = await res.json();
        if (data.success) {
          showGlobal('success', data.message);
          document.getElementById('register-btn').disabled = true;
          setTimeout(() => { window.location.href = '/'; }, 2000);
        } else {
          showGlobal('error', data.message);
          if (data.errors) {
            Object.entries(data.errors).forEach(([field, msg]) => {
              const map = { email:'email-error', password:'password-error', confirmPassword:'confirm-error', name:'name-error' };
              if (map[field]) showError(map[field], msg);
            });
          }
        }
      } catch (err) { showGlobal('error', 'Registration error: ' + err.message); }
    });
  </script></body></html>`);
});

// ─── Page: Reset Password ──────────────────────────────────────────────────
app.get('/reset-password', (req, res) => {
  res.send(`<!DOCTYPE html><html lang="en"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Reset Password - Test Application</title>
    <style>${sharedCSS}</style>
  </head><body><div class="card">
    <h1>Reset Password</h1>
    <div id="global-error" class="global-error" role="alert"></div>
    <div id="global-success" class="global-success"></div>
    <div class="field">
      <label for="email">Email</label>
      <input type="email" id="email" aria-label="Email" placeholder="Enter your email">
      <div class="error-msg" id="email-error"></div>
    </div>
    <button id="send-reset-btn">Send Reset Link</button>
    <div class="links"><a href="/">Back to Login</a></div>
  </div>
  <script>
    document.getElementById('send-reset-btn').addEventListener('click', async () => {
      const email = document.getElementById('email').value.trim();
      const errEl = document.getElementById('email-error');
      const ge = document.getElementById('global-error');
      const gs = document.getElementById('global-success');
      errEl.style.display='none'; ge.style.display='none'; gs.style.display='none';
      if (!email) { errEl.textContent='Email is required'; errEl.style.display='block'; return; }
      const res = await fetch('/api/reset-password', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ email })
      });
      const data = await res.json();
      if (data.success) { gs.textContent=data.message; gs.style.display='block'; }
      else { ge.textContent=data.message; ge.style.display='block'; }
    });
  </script></body></html>`);
});

// ─── Page: Reset Confirm ───────────────────────────────────────────────────
app.get('/reset-confirm', (req, res) => {
  res.send(`<!DOCTYPE html><html lang="en"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Set New Password - Test Application</title>
    <style>${sharedCSS}</style>
  </head><body><div class="card">
    <h1>Set New Password</h1>
    <div id="global-error" class="global-error"></div>
    <div id="global-success" class="global-success"></div>
    <div class="field">
      <label for="new-password">New Password</label>
      <input type="password" id="new-password" aria-label="New password" placeholder="Min 8 characters">
    </div>
    <div class="field">
      <label for="confirm-password">Confirm Password</label>
      <input type="password" id="confirm-password" aria-label="Confirm password" placeholder="Re-enter password">
      <div class="error-msg" id="match-error"></div>
    </div>
    <button id="reset-btn">Reset Password</button>
    <div id="reset-success" style="display:none;"><p>Password reset successfully!</p><a href="/">Back to Login</a></div>
  </div>
  <script>
    document.getElementById('reset-btn').addEventListener('click', async () => {
      const pw = document.getElementById('new-password').value;
      const cpw = document.getElementById('confirm-password').value;
      const me = document.getElementById('match-error');
      const ge = document.getElementById('global-error');
      me.style.display='none'; ge.style.display='none';
      if (pw !== cpw) { me.textContent='Passwords do not match'; me.style.display='block'; return; }
      const res = await fetch('/api/reset-confirm', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ password: pw, token: 'mock-token' })
      });
      const data = await res.json();
      if (data.success) { document.getElementById('reset-btn').style.display='none'; document.getElementById('reset-success').style.display='block'; }
      else { ge.textContent=data.message; ge.style.display='block'; }
    });
  </script></body></html>`);
});

// ─── Page: Boundary Test ───────────────────────────────────────────────────
app.get('/boundary-test', (req, res) => {
  res.send(`<!DOCTYPE html><html lang="en"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Boundary Test - Test Application</title>
    <style>${sharedCSS}</style>
  </head><body><div class="card">
    <h1>Boundary Test Page</h1>
    <form id="boundary-form">
      <div class="field">
        <label for="boundary-input">Test Input</label>
        <input type="text" id="boundary-input" name="boundary-input" placeholder="Enter value">
      </div>
      <button type="submit">Submit</button>
    </form>
    <div id="result" style="margin-top:12px;"></div>
  </div>
  <script>
    document.getElementById('boundary-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const val = document.getElementById('boundary-input').value;
      document.getElementById('result').textContent = 'Submitted: ' + val + ' (length: ' + val.length + ')';
    });
  </script></body></html>`);
});

// ─── Start ─────────────────────────────────────────────────────────────────
app.listen(port, () => {
  console.log(`Mock server running at http://localhost:${port}`);
  console.log('Available pages: / | /dashboard | /register | /reset-password | /reset-confirm | /boundary-test');
});