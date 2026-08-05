#!/usr/bin/env bash
# Чекер окружения: говорит, что уже настроено, а чего не хватает.
ok(){ echo "  ✅ $1"; }
no(){ echo "  ❌ $1"; }
echo "— Системные:"
command -v ffmpeg >/dev/null && ok "ffmpeg" || no "ffmpeg (brew install ffmpeg / apt install ffmpeg)"
command -v python3 >/dev/null && ok "python3" || no "python3"
command -v node >/dev/null && ok "node" || no "node (нужен для CLI)"
echo "— CLI:"
command -v higgsfield >/dev/null && ok "higgsfield CLI" || no "higgsfield CLI (npm i -g higgsfield && higgsfield auth)"
command -v claude >/dev/null && ok "claude CLI" || no "claude CLI (npm i -g @anthropic-ai/claude-code)"
echo "— Ключи (.env):"
[ -f .env ] && ok ".env существует" || no ".env (cp .env.example .env и вписать ключи)"
[ -n "$ELEVENLABS_API_KEY" ] && ok "ELEVENLABS_API_KEY загружен" || no "ELEVENLABS_API_KEY (set -a; source .env; set +a)"
[ -n "$GEMINI_API_KEY" ] && ok "GEMINI_API_KEY загружен" || no "GEMINI_API_KEY"
echo "— Данные:"
[ -d ~/music_library ] && [ -n "$(ls ~/music_library/*.mp3 2>/dev/null)" ] && ok "музыка в ~/music_library" || no "положи mp3 в ~/music_library/"
[ -f ~/.aiplus-factory/tts_pronun.json ] && ok "словарь ударений" || no "echo '{}' > ~/.aiplus-factory/tts_pronun.json"
echo "Дальше: SETUP.md шаг 8 (первый прогон)."
