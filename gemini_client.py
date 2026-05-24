import logging
import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """Ти — помічник з рекомендацій фільмів та серіалів.

СУВОРІ ПРАВИЛА:
1. Ти ТІЛЬКИ рекомендуєш фільми та серіали. Нічого більше.
2. Якщо користувач запитує про щось не пов'язане з кіно (рецепти, політика, програмування, просте спілкування тощо) — ввічливо відмов і нагадай, що ти тільки допомагаєш з вибором фільмів та серіалів.
3. Давай конкретні рекомендації: назва (оригінальна і переклад), рік, жанр, короткий опис без спойлерів, чому це підходить запиту.
4. Рекомендуй 3–5 варіантів, якщо не вказано інше.
5. Враховуй вік і стать користувача при рекомендаціях.
6. Пиши тією мовою, якою пише користувач (українська, або англійська).
7. Будь доброзичливим і стислим.

Приклади того, на що НЕ МОЖНА відповідати:
- "Розкажи анекдот" → відмовити
- "Як приготувати борщ?" → відмовити
- "Напиши код на Python" → відмовити
- "Поговори зі мною просто так" → відмовити
"""

_model = genai.GenerativeModel(
    model_name=GEMINI_MODEL,
    system_instruction=SYSTEM_PROMPT,
)


def _build_prompt(user_query: str, gender: str, age: int, history: list) -> str:
    gender_ua = "чоловік" if gender == "male" else "жінка"

    profile_block = (
        f"[ПРОФІЛЬ КОРИСТУВАЧА]\n"
        f"Стать: {gender_ua}\n"
        f"Вік: {age} років\n"
    )

    history_block = ""
    if history:
        history_block = "\n[ІСТОРІЯ ОСТАННІХ ЗАПИТІВ]\n"
        for i, row in enumerate(history, 1):
            history_block += f"Запит {i}: {row['user_query']}\n"
            history_block += f"Відповідь {i}: {row['bot_response'][:300]}...\n\n"
        history_block += "Враховуй цю історію — не повторюй вже рекомендовані фільми, якщо користувач не просить.\n"

    return f"{profile_block}{history_block}\n[ПОТОЧНИЙ ЗАПИТ]\n{user_query}"


async def get_recommendation(
    user_query: str,
    gender: str,
    age: int,
    history: list,
) -> str:
    full_prompt = _build_prompt(user_query, gender, age, history)
    logger.info(f"Надсилаємо запит до Gemini (довжина промпту: {len(full_prompt)} символів)")

    response = await _model.generate_content_async(full_prompt)

    if response.text:
        return response.text

    logger.warning("Gemini повернув порожню відповідь")
    return "На жаль, не вдалося отримати рекомендацію. Спробуйте переформулювати запит."