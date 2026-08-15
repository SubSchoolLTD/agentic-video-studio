# Админка: аналитика, экономика и промокоды

## Пользователи и деньги

Platform admin видит только клиентские аккаунты; сами platform admins не раздувают продуктовые метрики. В таблице пользователей доступны status, email verification, организация, роль, последний auth activity, текущий баланс, суммарные начисленные и потраченные AI tokens и внесённые USD.

`Deposited USD` считает только явные `balance_topup` и `admin_topup` с денежной суммой. Welcome tokens и promo credits не считаются выручкой. `Provider cost` отдельно суммирует настроенную себестоимость операций `ai_usage`, поэтому расход Google/Parallel больше не может случайно попасть в пополнения.

Ручное пополнение администратора сохраняет и tokens, и фактически полученные USD одной immutable ledger entry.

## D7 и D30 retention

Метрика намеренно rolling, а не exact-day:

```text
eligible_DN = customer account created_at <= now - N days
retained_DN = eligible account with any authenticated session activity >= created_at + N days
retention_DN = retained_DN / eligible_DN
```

Например, пользователь зарегистрировался в день 0 и снова авторизовался только в день 9: он входит в D7. Если вернулся в день 35, входит и в D7, и в D30. Аккаунты, которым ещё нет 7/30 дней, не попадают в соответствующий denominator.

## Управляемая цена AI-функций

Каждая тарифицируемая функция имеет отдельный price rule:

- provider и integration;
- model ID или связку моделей;
- расчётную provider cost в USD за unit;
- списание AI tokens за unit;
- целевую margin;
- active/inactive.

Отдельные правила есть для обычного видео с TTS, UGC с native Veo audio, обеих регенераций сцен и Gemini Image character. Изменение правила влияет только на новые списания; исторический ledger не переписывается.

## Промокоды

Администратор выпускает credit, subscription или bundle code, задаёт tokens, дни подписки, общее число активаций и срок действия. В базе хранится только hash полного кода и безопасный prefix. Один пользователь не может применить один код повторно.

Пользователь активирует код в Billing. Там же видит историю своих активаций; данные другого tenant недоступны.
