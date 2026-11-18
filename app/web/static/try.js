// Demo page: send the request to /api/try and render the assistant's tool calls.
// All text is inserted with textContent, never innerHTML, so tool output can't inject markup.
(() => {
  const form = document.getElementById("try-form");
  if (!form) return;

  const input = document.getElementById("try-message");
  const submit = document.getElementById("try-submit");
  const output = document.getElementById("try-output");
  const stepsList = document.getElementById("try-steps");
  const answer = document.getElementById("try-answer");

  document.querySelectorAll("[data-example]").forEach((chip) => {
    chip.addEventListener("click", () => {
      input.value = chip.dataset.example;
      input.focus();
    });
  });

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const renderStep = (step) => {
    const li = el("li", `step ${step.kind}${step.is_error ? " error" : ""}`);
    if (step.kind === "assistant") {
      li.append(el("span", "label", "Assistant"), el("p", "", step.text));
    } else if (step.kind === "tool_call") {
      li.append(el("span", "label", `Calls ${step.tool}`), el("pre", "", JSON.stringify(step.data, null, 2)));
    } else {
      const details = el("details");
      details.append(el("summary", "", `${step.tool} returned${step.is_error ? " an error" : ""}`));
      details.append(el("pre", "", typeof step.data === "string" ? step.data : JSON.stringify(step.data, null, 2)));
      li.append(details);
    }
    return li;
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    submit.textContent = "Thinking…";
    stepsList.replaceChildren();
    answer.textContent = "";
    output.hidden = false;

    try {
      const response = await fetch("/api/try", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ message: input.value }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Something went wrong.");
      data.steps.filter((s) => s.kind !== "assistant").forEach((s) => stepsList.append(renderStep(s)));
      answer.textContent = data.final_answer;
    } catch (err) {
      answer.textContent = err.message;
      answer.classList.add("error");
    } finally {
      submit.disabled = false;
      submit.textContent = "Ask the assistant";
    }
  });
})();
