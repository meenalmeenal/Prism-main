// mock-server.js
const express = require('express');
const app = express();
const port = 3000;

// Middleware to parse JSON bodies
app.use(express.json());

// Mock login endpoint
app.post('/api/login', (req, res) => {
  const { username, password } = req.body;
  
  if (username === 'testuser' && password === 'password') {
    return res.status(200).json({ 
      success: true, 
      token: 'mock-jwt-token',
      user: { id: 1, username: 'testuser' }
    });
  }
  
  return res.status(401).json({ 
    success: false, 
    message: 'Invalid credentials' 
  });
});

// Mock protected route
app.get('/api/protected', (req, res) => {
  const authHeader = req.headers.authorization;
  
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ 
      success: false, 
      message: 'No token provided' 
    });
  }
  
  return res.status(200).json({ 
    success: true, 
    data: 'Protected data' 
  });
});

// Reset password API
app.post('/api/reset-password', (req, res) => {
  const { email } = req.body;
  if (!email) return res.status(400).json({ success: false, message: 'Email is required' });
  res.status(200).json({ success: true, message: 'Reset link sent to ' + email });
});

// Reset confirm API
app.post('/api/reset-confirm', (req, res) => {
  const { password, token } = req.body;
  if (!password || !token) return res.status(400).json({ success: false, message: 'Missing fields' });
  if (password.length < 8) return res.status(400).json({ success: false, message: 'Password must be at least 8 characters' });
  res.status(200).json({ success: true, message: 'Password reset successfully' });
});

// Login page (root)
app.get('/', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html>
      <head>
        <title>Test Application</title>
      </head>
      <body>
        <h1>Welcome to the Test Application</h1>
        <div id="login-form">
          <input type="text" id="username" placeholder="Username">
          <input type="password" id="password" placeholder="Password">
          <button id="login-btn">Login</button>
          <br><br>
          <a id="forgot-password-link" href="/reset-password">Forgot Password</a>
        </div>
        <div id="protected-content" style="display: none;">
          <h2>Protected Content</h2>
          <p>This is only visible after login</p>
        </div>
        <script>
          document.getElementById('login-btn').addEventListener('click', async () => {
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            try {
              const response = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
              });
              const data = await response.json();
              if (data.success) {
                document.getElementById('login-form').style.display = 'none';
                document.getElementById('protected-content').style.display = 'block';
                localStorage.setItem('token', data.token);
              } else {
                alert('Login failed: ' + data.message);
              }
            } catch (error) {
              alert('Login error: ' + error.message);
            }
          });
        </script>
      </body>
    </html>
  `);
});

// Reset password page
app.get('/reset-password', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html>
      <head><title>Reset Password</title></head>
      <body>
        <h1>Reset Password</h1>
        <div id="reset-form">
          <input type="email" id="email" placeholder="Enter your email">
          <button id="send-reset-btn">Send Reset Link</button>
        </div>
        <div id="success-message" style="display:none;">
          <p>Password reset link sent to your email!</p>
          <a href="/">Back to Login</a>
        </div>
        <script>
          document.getElementById('send-reset-btn').addEventListener('click', async () => {
            const email = document.getElementById('email').value;
            const response = await fetch('/api/reset-password', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ email })
            });
            const data = await response.json();
            if (data.success) {
              document.getElementById('reset-form').style.display = 'none';
              document.getElementById('success-message').style.display = 'block';
            } else {
              alert('Error: ' + data.message);
            }
          });
        </script>
      </body>
    </html>
  `);
});

// Reset confirm page
app.get('/reset-confirm', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html>
      <head><title>Set New Password</title></head>
      <body>
        <h1>Set New Password</h1>
        <input type="password" id="new-password" placeholder="New password">
        <input type="password" id="confirm-password" placeholder="Confirm password">
        <button id="reset-btn">Reset Password</button>
        <div id="reset-success" style="display:none;">
          <p>Password reset successfully!</p>
          <a href="/">Back to Login</a>
        </div>
        <script>
          document.getElementById('reset-btn').addEventListener('click', async () => {
            const newPassword = document.getElementById('new-password').value;
            const confirmPassword = document.getElementById('confirm-password').value;
            if (newPassword !== confirmPassword) { alert('Passwords do not match'); return; }
            const response = await fetch('/api/reset-confirm', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ password: newPassword, token: 'mock-token' })
            });
            const data = await response.json();
            if (data.success) {
              document.getElementById('reset-btn').style.display = 'none';
              document.getElementById('reset-success').style.display = 'block';
            }
          });
        </script>
      </body>
    </html>
  `);
});

// Boundary test page
app.get('/boundary-test', (req, res) => {
  console.log('Serving boundary test page');
  res.send(`
    <!DOCTYPE html>
    <html>
      <head><title>Boundary Test Page</title></head>
      <body>
        <h1>Boundary Test Page</h1>
        <form id="boundary-form">
          <input type="text" id="boundary-input" name="boundary-input" placeholder="Enter value">
          <button type="submit">Submit</button>
        </form>
        <div id="result"></div>
      </body>
    </html>
  `);
});

app.listen(port, () => {
  console.log(`Mock server running at http://localhost:${port}`);
});