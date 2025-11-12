# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2025-11-10

### 🎉 Major Redesign

#### Added
- ✨ Complete UI redesign with modern, professional interface
- 🎨 Beautiful gradient theme with glass-morphism effects
- 📱 Responsive navigation with 8 main sections
- 🚪 Door icon in browser tab
- 🔔 Toast notifications for all actions
- 📊 Dashboard with real-time statistics
- 👥 User management with full CRUD operations
- 📋 Board management with door configuration
- 🚪 Door access groups
- 📅 Time schedules
- 📝 Access logs with filtering
- 📡 Live monitor (coming soon)
- 🔄 Direct HTTP communication with ESP32 boards
- ⚡ Emergency unlock/lock buttons

#### Changed
- 🏗️ Complete architecture redesign
- 💾 Updated database schema with board_doors table
- 🔧 Improved API endpoints with better error handling
- 📝 All responses include success messages
- 🎯 Better logging with emojis

#### Fixed
- 🐛 Database initialization issues
- 🔒 Token handling improvements
- 🔄 Template caching problems

### Technical Details
- Removed dependency on ESPHome services
- Direct ESP32 communication via HTTP
- Professional UI using Tailwind CSS
- Toast notifications for user feedback
- Proper error handling throughout

## [1.0.0] - 2025-11-01

### Initial Release
- Basic access control functionality
- Simple web interface
- ESPHome integration
- User and card management
