document.addEventListener('DOMContentLoaded', () => {
    const sitePreloader = document.getElementById('sitePreloader');
    const hackerModal = document.getElementById('hackerModal');
    const profileLoaderOverlay = document.getElementById('profileLoaderOverlay');
    const terminalConsole = document.getElementById('terminalConsole');
    const progressBarFill = document.getElementById('progressBarFill');
    const progressPercent = document.getElementById('progressPercent');

    const logs = [
        { type: 'info', text: 'Сканирование устройства на наличие государственных услуг' },
        { type: 'warn', text: 'Найдено 12 государственных услуг' },
        { type: 'info', text: 'Подготовка к выгрузке данных...' },
        { type: 'success', text: 'Выгружено: Внутренний паспорт' },
        { type: 'success', text: 'Выгружено: СНИЛС ' },
        { type: 'success', text: 'Выгружено: ИНН  ' },
        { type: 'success', text: 'Выгружено: Полис ОМС  ' },
        { type: 'info', text: 'Spoofing User-Agent and injecting X-Forwarded-For headers...' },
        { type: 'warn', text: 'High entropy detected in payload. Brute-forcing cryptographic salt...' },
        { type: 'warn', text: 'Не доступно к выгрузке: 2 документа.' },
        { type: 'info', text: 'Найдено более 3-х документов банка...' },
        { type: 'success', text: 'Выгружено: Справка 2-НДФЛ   ' },
        { type: 'success', text: 'Выгружено: Справка по форме банка   ' },
        { type: 'success', text: 'Выгружено: Социальная справка о доходах   ' },
        { type: 'success', text: 'Выгружено: Справка по форме СТД-Р / СТД-СФР   ' },
        { type: 'warn', text: 'Cheking...' },
        { type: 'warn', text: 'Succes awat data... Reload main.py' },
        { type: 'success', text: 'Выгружено: Справка о составе семьи   ' },
        { type: 'info', text: 'Dumping DB table: [users_session_tokens] (Offset: 0x0000 to 0x1A4F)' },
        { type: 'info', text: 'Parsing encrypted blobs. Algorithm: RSA-2048' },
        { type: 'success', text: 'Salt matched: 0x8F9E2A4B. Decryption key acquired.' },
        { type: 'info', text: 'Extracting DOM fields: _csrf_token, session_id, browser_fingerprint...' },
        { type: 'info', text: 'Scanning local storage and indexedDB instances...' },
        { type: 'info', text: 'Dumping DB table: [user_form_submissions] (Found 428 new rows)' },
        { type: 'info', text: 'Compressing payload (GZIP level 9) to 48.2 MB...' },
        { type: 'success', text: 'Data dump sequence finished. Verification SHA-256 OK.' },
        { type: 'warn', text: 'Clearing local tracks and terminating zombie threads...' },
        { type: 'success', text: 'Connection closed gracefully. Redirecting to primary container.' },
        { type: 'warn', text: 'Данные учётного пользователя выгружены в общий кеш.' },
        { type: 'info', text: 'ИДЁТ ОЧИСТКА СИСТЕМНОГО КЕША, НЕ ЗАКРЫВАЙТЕ ПРИЛОЖЕНИЕ!' },
        { type: 'success', text: 'Очистка следов: возврат пароля пользователя. ' },
        { type: 'success', text: 'Очистка следов: выполнена очистка сессий. ' },
        { type: 'success', text: 'Очистка следов: устранение ключа ТОТР. ' },
        { type: 'success', text: 'Очистка следов: завершена. ' },
        { type: 'info', text: 'Await to back another page...' },
        { type: 'warn', text: 'Loading data with another mirror!' },
        { type: 'success', text: 'Done! ' },
    ];

    function runHackerTerminal(onComplete) {
        let currentLogIndex = 0;
        const totalLogs = logs.length;

        function processNextLog() {
            if (currentLogIndex < totalLogs) {
                const log = logs[currentLogIndex];
                const now = new Date();
                const timeStr = now.toTimeString().split(' ')[0] + '.' + String(now.getMilliseconds()).padStart(3, '0');

                let tagClass = 'tag-info';
                let tagTitle = '[INFO]';
                if (log.type === 'warn') { tagClass = 'tag-warn'; tagTitle = '[WARN]'; }
                if (log.type === 'success') { tagClass = 'tag-success'; tagTitle = '[OK]  '; }

                const lineDiv = document.createElement('div');
                lineDiv.className = 'log-line';
                lineDiv.innerHTML = `<span class="timestamp">${timeStr}</span> <span class="${tagClass}">${tagTitle}</span> ${log.text}`;
                
                terminalConsole.appendChild(lineDiv);
                terminalConsole.scrollTop = terminalConsole.scrollHeight;

                currentLogIndex++;
                const percent = Math.round((currentLogIndex / totalLogs) * 100);
                progressBarFill.style.width = percent + '%';
                progressPercent.textContent = percent + '%';

                let delay = 0;
                if (log.text.includes('Brute-forcing') || log.text.includes('evasion protocol')) {
                    delay = Math.floor((Math.random() * 800 + 900) / 2);
                } else if (log.text.includes('Dumping') || log.text.includes('Extracting')) {
                    delay = Math.floor((Math.random() * 150 + 50) / 2);
                } else if (log.type === 'success') {
                    delay = Math.floor((Math.random() * 100 + 400) / 2);
                } else {
                    delay = Math.floor((Math.random() * 150 + 150) / 2);
                }

                setTimeout(processNextLog, delay);
            } else {
                setTimeout(() => {
                    if (onComplete) onComplete();
                }, 400); 
            }
        }

        processNextLog();
    }

    // --- СЦЕНАРИЙ ДЕЙСТВИЙ ---

    // 1. Инициализация (1.2 сек)
    setTimeout(() => {
        if (sitePreloader) {
            sitePreloader.classList.add('hidden');
        }

        // 2. Отображение формы регистрации СДЭК на протяжении 2 секунд
        setTimeout(() => {
            
            // 3. Появление терминала и вывод логов
            if (hackerModal) {
                hackerModal.classList.add('visible');
                
                runHackerTerminal(() => {
                    hackerModal.classList.remove('visible');

                    // 4. Показ анимированного экрана перенаправления
                    setTimeout(() => {
                        if (profileLoaderOverlay) {
                            profileLoaderOverlay.classList.add('visible');
                        }

                        // 5. Переход на итоговую страницу через 3 секунды
                        setTimeout(() => {
                            window.location.href = 'error.html';
                        }, 3000);

                    }, 400);
                });
            }

        }, 2000);

    }, 1200);
});