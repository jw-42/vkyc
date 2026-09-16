"""
vkyc — платформенные примитивы для бэкенда VK Mini Apps на связке
Yandex Cloud Functions + YDB: верификация VK launch-params и JWT, форма
HTTP-ответа и логирование под Cloud Functions, CRUD-примитивы поверх YDB
Document API, подписки VK Pay и тарифы.

Импортировать нужно конкретный подпакет (`from vkyc.auth import ...`), а не
пакет целиком — здесь ничего не реэкспортируется.
"""
