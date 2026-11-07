const form = document.querySelector("#patient-form");
const formTitle = document.querySelector("#form-title");
const formError = document.querySelector("#form-error");
const submitButton = document.querySelector("#submit-button");
const cancelButton = document.querySelector("#cancel-edit");
const pageMessage = document.querySelector("#page-message");
const recordsBody = document.querySelector("#records-body");
const tableWrap = document.querySelector("#table-wrap");
const emptyState = document.querySelector("#empty-state");
const loading = document.querySelector("#loading");
const recordCount = document.querySelector("#record-count");

const fields = {
  id: document.querySelector("#patient-id"),
  full_name: document.querySelector("#full-name"),
  dob: document.querySelector("#dob"),
  email: document.querySelector("#email"),
  glucose: document.querySelector("#glucose"),
  haemoglobin: document.querySelector("#haemoglobin"),
  cholesterol: document.querySelector("#cholesterol"),
};

function showMessage(element, message, success = false) {
  element.textContent = message;
  element.classList.toggle("success", success);
  element.hidden = false;
}

function clearMessage(element) {
  element.textContent = "";
  element.hidden = true;
  element.classList.remove("success");
}

function formatNumber(value) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

function errorText(data, fallback) {
  if (typeof data?.detail === "string") return data.detail;
  if (Array.isArray(data?.detail)) {
    return data.detail.map((item) => {
      const location = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
      return `${location ? `${location}: ` : ""}${item.msg}`;
    }).join(" ");
  }
  return fallback;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(errorText(data, `Request failed (${response.status}).`));
  return data;
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderPatient(patient) {
  const row = document.createElement("tr");

  const identity = document.createElement("td");
  identity.append(
    makeElement("span", "patient-name", patient.full_name),
    makeElement("span", "patient-meta", patient.email),
    makeElement("span", "patient-meta", `Born ${patient.dob}`),
  );

  const measurements = document.createElement("td");
  const values = makeElement("div", "measurement-lines");
  for (const [label, value] of [
    ["Glucose", patient.glucose],
    ["Haemoglobin", patient.haemoglobin],
    ["Cholesterol", patient.cholesterol],
  ]) {
    const line = document.createElement("div");
    line.append(makeElement("strong", "", label), ` ${formatNumber(value)}`);
    values.append(line);
  }
  measurements.append(values);

  const remarks = document.createElement("td");
  const source = makeElement(
    "span",
    `remark-source${patient.remark_source === "External AI" ? " external" : ""}`,
    patient.remark_source,
  );
  remarks.append(source, makeElement("div", "remark-text", patient.remarks));
  if (patient.remark_notice) {
    remarks.append(makeElement("div", "remark-notice", patient.remark_notice));
  }

  const actions = document.createElement("td");
  const actionList = makeElement("div", "row-actions");
  const edit = makeElement("button", "action-button", "Edit");
  edit.type = "button";
  edit.addEventListener("click", () => beginEdit(patient));
  const remove = makeElement("button", "action-button delete", "Delete");
  remove.type = "button";
  remove.addEventListener("click", () => deletePatient(patient));
  actionList.append(edit, remove);
  actions.append(actionList);

  row.append(identity, measurements, remarks, actions);
  return row;
}

async function loadPatients() {
  loading.hidden = false;
  tableWrap.hidden = true;
  emptyState.hidden = true;
  try {
    const patients = await request("/api/patients");
    recordsBody.replaceChildren(...patients.map(renderPatient));
    recordCount.textContent = String(patients.length);
    tableWrap.hidden = patients.length === 0;
    emptyState.hidden = patients.length !== 0;
    clearMessage(pageMessage);
  } catch (error) {
    showMessage(pageMessage, `Could not load records: ${error.message}`);
  } finally {
    loading.hidden = true;
  }
}

function formValues() {
  return {
    full_name: fields.full_name.value.trim(),
    dob: fields.dob.value.trim(),
    email: fields.email.value.trim(),
    glucose: fields.glucose.value,
    haemoglobin: fields.haemoglobin.value,
    cholesterol: fields.cholesterol.value,
  };
}

function resetForm() {
  form.reset();
  fields.id.value = "";
  formTitle.textContent = "Add a patient";
  submitButton.textContent = "Save patient";
  cancelButton.hidden = true;
  clearMessage(formError);
}

function beginEdit(patient) {
  fields.id.value = String(patient.id);
  fields.full_name.value = patient.full_name;
  fields.dob.value = patient.dob;
  fields.email.value = patient.email;
  fields.glucose.value = patient.glucose;
  fields.haemoglobin.value = patient.haemoglobin;
  fields.cholesterol.value = patient.cholesterol;
  formTitle.textContent = "Edit patient";
  submitButton.textContent = "Save changes";
  cancelButton.hidden = false;
  clearMessage(formError);
  form.scrollIntoView({ behavior: "smooth", block: "start" });
  fields.full_name.focus();
}

async function deletePatient(patient) {
  if (!window.confirm(`Delete the record for ${patient.full_name}? This cannot be undone.`)) return;
  try {
    await request(`/api/patients/${patient.id}`, { method: "DELETE" });
    showMessage(pageMessage, `${patient.full_name}'s record was deleted.`, true);
    await loadPatients();
  } catch (error) {
    showMessage(pageMessage, `Could not delete record: ${error.message}`);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearMessage(formError);
  if (!form.reportValidity()) return;

  const patientId = fields.id.value;
  const method = patientId ? "PUT" : "POST";
  const path = patientId ? `/api/patients/${patientId}` : "/api/patients";
  submitButton.disabled = true;
  try {
    const patient = await request(path, {
      method,
      body: JSON.stringify(formValues()),
    });
    resetForm();
    showMessage(
      pageMessage,
      patientId ? `${patient.full_name}'s record was updated.` : `${patient.full_name} was added.`,
      true,
    );
    await loadPatients();
  } catch (error) {
    showMessage(formError, error.message);
  } finally {
    submitButton.disabled = false;
  }
});

cancelButton.addEventListener("click", resetForm);
document.querySelector("#refresh-button").addEventListener("click", loadPatients);
loadPatients();
