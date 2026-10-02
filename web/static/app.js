// Небольшие улучшения поверх обычных форм: сайт работает и без JavaScript.

document.addEventListener("submit", (event) => {
  // Формы с data-confirm спрашивают подтверждение (удаление, списание всего).
  const form = event.target.closest("form[data-confirm]");
  if (form && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
  }
});

// Поле «Другая причина» видно, только когда выбрана эта причина.
document.querySelectorAll("[data-reason-group]").forEach((group) => {
  const text = group.querySelector(".reason-text");
  const update = () => {
    const other = group.querySelector('input[value="other"]').checked;
    text.hidden = !other;
    text.required = other;
    if (other) text.focus();
  };
  group.addEventListener("change", update);
  text.hidden = !group.querySelector('input[value="other"]').checked;
});
