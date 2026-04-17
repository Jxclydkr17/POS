from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QMessageBox, QComboBox, QListWidget, QScrollArea, QWidget,
    QTextEdit, QDateEdit, QCheckBox
)
from PySide6.QtCore import Qt, QDate
from ui.session_manager import session
from ui.utils.http_worker import api_call
from ui.api import API

VALID_STYLE = "border: 2px solid #28a745; border-radius: 5px; padding: 3px;"   # Verde
INVALID_STYLE = "border: 2px solid #dc3545; border-radius: 5px; padding: 3px;" # Rojo
NORMAL_STYLE = "border: 1px solid #444; border-radius: 5px; padding: 3px;"     # Normal


def _auth_headers():
    return {"Authorization": f"Bearer {session.token}"}


class AddCustomerDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Agregar Cliente")
        self.setMinimumWidth(760)
        self.setMinimumHeight(620)
        self.resize(820, 700)
        self.setStyleSheet("background-color: #1E1E1E; color: white;")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # -----------------------------
        # CREAR CAMPOS ANTES DEL LAYOUT
        # -----------------------------
        self.name_input = QLineEdit()
        self.email_input = QLineEdit()
        self.phone_input = QLineEdit()
        self.address_input = QLineEdit()

        self.id_type_combo = QComboBox()
        self.id_type_combo.addItems(["Física", "Jurídica", "DIMEX"])

        self.id_number_input = QLineEdit()
        self.id_type_combo.currentTextChanged.connect(self.update_id_mask)

        # Aplicar máscara inicial
        self.update_id_mask(self.id_type_combo.currentText())

        self.credit_limit_input = QLineEdit()
        self.credit_limit_input.setPlaceholderText("0 = sin límite")

        self.has_credit_limit_chk = QCheckBox("Tiene límite de crédito")
        self.has_credit_limit_chk.setChecked(False)
        self.has_credit_limit_chk.toggled.connect(
            lambda checked: self.credit_limit_input.setEnabled(checked)
        )
        self.credit_limit_input.setEnabled(False)

        # Teléfono secundario
        self.secondary_phone_input = QLineEdit()
        self.secondary_phone_input.setPlaceholderText("Trabajo, familiar, etc.")

        # Tipo de cliente
        self.customer_type_combo = QComboBox()
        self.customer_type_combo.addItems([
            "Normal", "Mayorista", "VIP", "Exento", "Corporativo"
        ])

        # Notas internas
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Notas internas (ej: prefiere SINPE, paga tarde...)")
        self.notes_input.setMaximumHeight(70)

        # Fecha de nacimiento
        self.birth_date_input = QDateEdit()
        self.birth_date_input.setCalendarPopup(True)
        self.birth_date_input.setDisplayFormat("dd/MM/yyyy")
        self.birth_date_input.setDate(QDate(2000, 1, 1))
        self.birth_date_chk = QCheckBox("Registrar fecha de nacimiento")
        self.birth_date_chk.setChecked(False)
        self.birth_date_chk.toggled.connect(
            lambda checked: self.birth_date_input.setEnabled(checked)
        )
        self.birth_date_input.setEnabled(False)

        # Campos de ubicación
        self.province_combo = QComboBox()
        self.province_combo.currentIndexChanged.connect(self.on_province_changed)

        self.canton_combo = QComboBox()
        self.canton_combo.currentIndexChanged.connect(self.on_canton_changed)

        self.district_combo = QComboBox()

        self.neighborhood_input = QLineEdit()

        # Campos de actividades económicas
        self.activity_search_input = QLineEdit()
        self.activity_search_input.setPlaceholderText("Buscar por código o descripción...")
        self.activity_search_input.textChanged.connect(self.search_activities)

        self.activity_results_combo = QComboBox()

        self.btn_add_activity = QPushButton("Agregar actividad")
        self.btn_add_activity.clicked.connect(self.add_selected_activity)
        self.btn_add_activity.setStyleSheet("background-color: #28a745; padding: 4px; border-radius: 3px;")

        self.activities_list = QListWidget()
        self.activities_list.setMinimumHeight(140)

        self.btn_remove_activity = QPushButton("Eliminar actividad seleccionada")
        self.btn_remove_activity.clicked.connect(self.remove_selected_activity)
        self.btn_remove_activity.setStyleSheet("background-color: #dc3545; padding: 4px; border-radius: 3px;")

        # -----------------------------
        # SCROLL AREA PARA FORMULARIO
        # -----------------------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        form_layout = QHBoxLayout(content)
        form_layout.setSpacing(16)
        form_layout.setContentsMargins(0, 0, 0, 0)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        # --------- COLUMNA IZQUIERDA (datos básicos + crédito) ----------
        left_col.addWidget(QLabel("Nombre:"))
        left_col.addWidget(self.name_input)

        left_col.addWidget(QLabel("Correo:"))
        left_col.addWidget(self.email_input)

        left_col.addWidget(QLabel("Teléfono:"))
        left_col.addWidget(self.phone_input)

        left_col.addWidget(QLabel("Teléfono secundario:"))
        left_col.addWidget(self.secondary_phone_input)

        left_col.addWidget(QLabel("Dirección:"))
        left_col.addWidget(self.address_input)

        left_col.addWidget(QLabel("Tipo de identificación:"))
        left_col.addWidget(self.id_type_combo)

        left_col.addWidget(QLabel("Número de identificación:"))
        left_col.addWidget(self.id_number_input)

        left_col.addWidget(QLabel("Tipo de cliente:"))
        left_col.addWidget(self.customer_type_combo)

        left_col.addWidget(self.has_credit_limit_chk)
        left_col.addWidget(QLabel("Límite de crédito (₡):"))
        left_col.addWidget(self.credit_limit_input)

        left_col.addWidget(self.birth_date_chk)
        left_col.addWidget(self.birth_date_input)

        left_col.addWidget(QLabel("Notas internas:"))
        left_col.addWidget(self.notes_input)

        left_col.addStretch(1)

        # --------- COLUMNA DERECHA (ubicación + actividades) ----------
        right_col.addWidget(QLabel("Provincia:"))
        right_col.addWidget(self.province_combo)

        right_col.addWidget(QLabel("Cantón:"))
        right_col.addWidget(self.canton_combo)

        right_col.addWidget(QLabel("Distrito:"))
        right_col.addWidget(self.district_combo)

        right_col.addWidget(QLabel("Barrio:"))
        right_col.addWidget(self.neighborhood_input)

        right_col.addWidget(QLabel("Actividades Económicas:"))
        right_col.addWidget(self.activity_search_input)
        right_col.addWidget(self.activity_results_combo)
        right_col.addWidget(self.btn_add_activity)

        right_col.addWidget(QLabel("Actividades seleccionadas:"))
        right_col.addWidget(self.activities_list)
        right_col.addWidget(self.btn_remove_activity)

        right_col.addStretch(1)

        form_layout.addLayout(left_col, 1)
        form_layout.addLayout(right_col, 1)

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # --------- BOTONES SIEMPRE VISIBLES ABAJO ----------
        self.save_btn = QPushButton("Guardar")
        self.save_btn.clicked.connect(self.save_customer)
        self.save_btn.setStyleSheet("background-color: #0078D4; padding: 6px; border-radius: 5px;")

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("background-color: #444; padding: 6px; border-radius: 5px;")

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(cancel_btn)
        main_layout.addLayout(btn_layout)
        
        # Cargar provincias al abrir el diálogo
        self.load_provinces()

    # --------------------------------------------------------
    # GUARDAR CLIENTE → BACKEND
    # --------------------------------------------------------
    def save_customer(self):
        name = self.name_input.text().strip()

        if not name:
            QMessageBox.warning(self, "Error", "El nombre es obligatorio.")
            return

        # Validar teléfono CR (8 dígitos si se ingresó)
        phone = self.phone_input.text().strip()
        if phone and not phone.isdigit():
            QMessageBox.warning(self, "Error", "El teléfono debe contener solo dígitos.")
            return
        if phone and len(phone) != 8:
            QMessageBox.warning(self, "Error", "El teléfono debe tener 8 dígitos (formato CR).")
            return

        sec_phone = self.secondary_phone_input.text().strip()
        if sec_phone and not sec_phone.isdigit():
            QMessageBox.warning(self, "Error", "El teléfono secundario debe contener solo dígitos.")
            return
        if sec_phone and len(sec_phone) != 8:
            QMessageBox.warning(self, "Error", "El teléfono secundario debe tener 8 dígitos.")
            return

        # ✅ Validar límite de crédito con try-catch
        credit_limit_raw = self.credit_limit_input.text().strip()
        try:
            credit_limit = float(credit_limit_raw) if credit_limit_raw else 0.0
        except ValueError:
            QMessageBox.warning(self, "Error", "El límite de crédito debe ser un número válido.")
            return

        # Obtener datos de ubicación
        province_id = self.province_combo.currentData()
        # ✅ No guardar "— Seleccione —" como nombre
        province_name = self.province_combo.currentText() if province_id and province_id != "None" else None

        canton_id = self.canton_combo.currentData()
        canton_name = self.canton_combo.currentText() if canton_id and canton_id != "None" else None

        district_id = self.district_combo.currentData()
        district_name = self.district_combo.currentText() if district_id and district_id != "None" else None

        # has_credit_limit y birth_date
        has_credit_limit = self.has_credit_limit_chk.isChecked()

        birth_date = None
        if self.birth_date_chk.isChecked():
            birth_date = self.birth_date_input.date().toString("yyyy-MM-dd")

        payload = {
            "name": name,
            "email": self.email_input.text().strip() or None,
            "phone": phone or None,
            "secondary_phone": sec_phone or None,
            "address": self.address_input.text().strip() or None,
            "id_type": self.id_type_combo.currentText(),
            "id_number": self.id_number_input.text().strip() or None,
            "customer_type": self.customer_type_combo.currentText(),
            "credit_limit": credit_limit,
            "has_credit_limit": has_credit_limit,
            "notes": self.notes_input.toPlainText().strip() or None,
            "birth_date": birth_date,
            "province_id": province_id,
            "province_name": province_name,
            "canton_id": canton_id,
            "canton_name": canton_name,
            "district_id": district_id,
            "district_name": district_name,
            "neighborhood": self.neighborhood_input.text().strip() or None,
            "economic_activity_codes": self.get_activity_codes(),
        }

        headers = _auth_headers()

        # 🔄 Spinner: deshabilitar botón y cambiar texto
        self.save_btn.setEnabled(False)
        self.save_btn.setText("⏳ Guardando...")

        api_call(
            "post", API["customers"], json=payload, headers=headers,
            on_success=self._on_customer_saved,
            on_error=lambda msg: QMessageBox.warning(self, "Error", f"No se pudo agregar el cliente.\n\n{msg}"),
            on_finished=self._on_save_finished,
        )

    def _on_customer_saved(self, data):
        QMessageBox.information(self, "Éxito", "Cliente agregado correctamente.")
        self.accept()

    def _on_save_finished(self):
        self.save_btn.setEnabled(True)
        self.save_btn.setText("Guardar")

    def update_id_mask(self, id_type):
        if id_type == "Física":
            self.required_length = 9
            self.id_number_input.setInputMask("999999999;_")
        elif id_type == "Jurídica":
            self.required_length = 10
            self.id_number_input.setInputMask("9999999999;_")
        elif id_type == "DIMEX":
            self.required_length = 12
            self.id_number_input.setInputMask("999999999999;_")
        else:
            self.required_length = 0
            self.id_number_input.setInputMask("")

        self.validate_id_number()

    def validate_id_number(self):
        text = self.id_number_input.text().replace("_", "")

        if self.required_length == 0:
            self.id_number_input.setStyleSheet(NORMAL_STYLE)
            return

        if len(text) == 0:
            self.id_number_input.setStyleSheet(NORMAL_STYLE)
        elif len(text) < self.required_length:
            self.id_number_input.setStyleSheet(INVALID_STYLE)
        else:
            self.id_number_input.setStyleSheet(VALID_STYLE)

    # --------------------------------------------------------
    # MÉTODOS PARA UBICACIÓN GEOGRÁFICA
    # --------------------------------------------------------
    def load_provinces(self):
        api_call(
            "get", API["provinces"], headers=_auth_headers(),
            on_success=self._on_provinces_loaded,
            on_error=lambda msg: QMessageBox.warning(self, "Error", f"No se pudieron cargar las provincias: {msg}"),
        )

    def _on_provinces_loaded(self, data):
        self.province_combo.clear()
        self.province_combo.addItem("— Seleccione —", None)
        if isinstance(data, dict):
            for pid, name in data.items():
                self.province_combo.addItem(name, pid)

    def on_province_changed(self):
        pid = self.province_combo.currentData()
        self.canton_combo.clear()
        self.district_combo.clear()
        self.canton_combo.addItem("— Seleccione —", None)
        self.district_combo.addItem("— Seleccione —", None)
        if not pid:
            return
        api_call(
            "get", API["cantons"](pid), headers=_auth_headers(),
            on_success=self._on_cantons_loaded,
            on_error=lambda msg: QMessageBox.warning(self, "Error", f"No se pudieron cargar los cantones: {msg}"),
        )

    def _on_cantons_loaded(self, data):
        if isinstance(data, dict):
            for cid, name in data.items():
                self.canton_combo.addItem(name, cid)

    def on_canton_changed(self):
        pid = self.province_combo.currentData()
        cid = self.canton_combo.currentData()
        self.district_combo.clear()
        self.district_combo.addItem("— Seleccione —", None)
        if not pid or not cid:
            return
        api_call(
            "get", API["districts"](pid, cid), headers=_auth_headers(),
            on_success=self._on_districts_loaded,
            on_error=lambda msg: QMessageBox.warning(self, "Error", f"No se pudieron cargar los distritos: {msg}"),
        )

    def _on_districts_loaded(self, data):
        if isinstance(data, dict):
            for did, name in data.items():
                self.district_combo.addItem(name, did)

    # --------------------------------------------------------
    # MÉTODOS PARA ACTIVIDADES ECONÓMICAS
    # --------------------------------------------------------
    def search_activities(self):
        q = self.activity_search_input.text().strip()
        if len(q) < 2:
            self.activity_results_combo.clear()
            return
        url = API["economic_activity_search"](q)
        api_call(
            "get", url, headers=_auth_headers(),
            on_success=self._on_activities_found,
        )

    def _on_activities_found(self, results):
        self.activity_results_combo.clear()
        if isinstance(results, list):
            for it in results:
                label = f'{it["code"]} - {it["description"][:60]}'
                self.activity_results_combo.addItem(label, it["code"])

    def add_selected_activity(self):
        code = self.activity_results_combo.currentData()
        if not code:
            return
        # evitar duplicados
        existing = [self.activities_list.item(i).text().split(" - ")[0] for i in range(self.activities_list.count())]
        if code in existing:
            QMessageBox.information(self, "Información", "Esta actividad ya está agregada.")
            return
        # Agregar el texto completo del combo
        text = self.activity_results_combo.currentText()
        self.activities_list.addItem(text)

    def remove_selected_activity(self):
        row = self.activities_list.currentRow()
        if row >= 0:
            self.activities_list.takeItem(row)

    def get_activity_codes(self):
        codes = []
        for i in range(self.activities_list.count()):
            text = self.activities_list.item(i).text().strip()
            # Extraer el código (antes del " - ")
            code = text.split(" - ")[0] if " - " in text else text
            codes.append(code)
        return codes