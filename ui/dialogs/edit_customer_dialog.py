from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QMessageBox, QListWidget, QScrollArea, QWidget,
    QTextEdit, QDateEdit, QCheckBox
)
from PySide6.QtCore import Qt, QDate, QTimer
from ui.session_manager import session
from ui.utils.http_worker import api_call, run_async
from ui.api import API

VALID_STYLE = "border: 2px solid #28a745; border-radius: 5px; padding: 3px;"   # Verde
INVALID_STYLE = "border: 2px solid #dc3545; border-radius: 5px; padding: 3px;" # Rojo
NORMAL_STYLE = "border: 1px solid #444; border-radius: 5px; padding: 3px;"     # Normal


def _auth_headers():
    return {"Authorization": f"Bearer {session.token}"}


class EditCustomerDialog(QDialog):
    def __init__(self, customer_data):
        super().__init__()
        
        # ✅ Soportar backend que devuelva {"data": {...}}
        if isinstance(customer_data, dict) and "data" in customer_data and isinstance(customer_data["data"], dict):
            customer_data = customer_data["data"]
        
        self.customer_data = customer_data

        self.setWindowTitle("Editar Cliente")
        self.setMinimumWidth(760)
        self.setMinimumHeight(620)
        self.resize(820, 700)
        self.setStyleSheet("background-color: #1E1E1E; color: white;")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # ------------------------------------------------------
        # CREAR CAMPOS ANTES DEL LAYOUT
        # ------------------------------------------------------
        self.name_input = QLineEdit(customer_data.get("name", ""))
        self.email_input = QLineEdit(customer_data.get("email", ""))
        self.phone_input = QLineEdit(customer_data.get("phone", ""))
        self.address_input = QLineEdit(customer_data.get("address", ""))

        self.id_type_combo = QComboBox()
        self.id_type_combo.addItems(["Física", "Jurídica", "DIMEX"])

        self.id_number_input = QLineEdit()
        self.id_type_combo.currentTextChanged.connect(self.update_id_mask)

        # Establecer tipo guardado
        saved_type = customer_data.get("id_type", "Física")
        idx = self.id_type_combo.findText(saved_type)
        self.id_type_combo.setCurrentIndex(idx if idx != -1 else 0)

        # Aplicar máscara inicial
        self.update_id_mask(self.id_type_combo.currentText())

        # Establecer número de ID guardado
        self.id_number_input.setText(customer_data.get("id_number", ""))

        # ── FASE 5: Debounce para lookup de cédula en Hacienda ──
        # Se conecta DESPUÉS del setText para no disparar lookup al abrir.
        self._lookup_timer = QTimer()
        self._lookup_timer.setSingleShot(True)
        self._lookup_timer.setInterval(600)
        self._lookup_timer.timeout.connect(self._do_cedula_lookup)
        self.id_number_input.textChanged.connect(lambda: self._lookup_timer.start())

        # Label de estado del lookup
        self.cedula_status_label = QLabel("")
        self.cedula_status_label.setWordWrap(True)
        self.cedula_status_label.setStyleSheet("font-size: 11px; padding: 2px 0;")

        # Campo de límite de crédito
        self.credit_limit_input = QLineEdit(str(customer_data.get("credit_limit", 0.0)))
        self.credit_limit_input.setPlaceholderText("0 = sin límite")

        self.has_credit_limit_chk = QCheckBox("Tiene límite de crédito")
        saved_has_limit = bool(customer_data.get("has_credit_limit", False))
        self.has_credit_limit_chk.setChecked(saved_has_limit)
        self.has_credit_limit_chk.toggled.connect(
            lambda checked: self.credit_limit_input.setEnabled(checked)
        )
        self.credit_limit_input.setEnabled(saved_has_limit)

        # Teléfono secundario
        self.secondary_phone_input = QLineEdit(customer_data.get("secondary_phone", "") or "")
        self.secondary_phone_input.setPlaceholderText("Trabajo, familiar, etc.")

        # Tipo de cliente
        self.customer_type_combo = QComboBox()
        self.customer_type_combo.addItems([
            "Normal", "Mayorista", "VIP", "Exento", "Corporativo"
        ])
        saved_ct = customer_data.get("customer_type", "Normal") or "Normal"
        ct_idx = self.customer_type_combo.findText(saved_ct)
        self.customer_type_combo.setCurrentIndex(ct_idx if ct_idx != -1 else 0)

        # Notas internas
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Notas internas (ej: prefiere SINPE, paga tarde...)")
        self.notes_input.setMaximumHeight(70)
        self.notes_input.setPlainText(customer_data.get("notes", "") or "")

        # Fecha de nacimiento
        self.birth_date_input = QDateEdit()
        self.birth_date_input.setCalendarPopup(True)
        self.birth_date_input.setDisplayFormat("dd/MM/yyyy")
        self.birth_date_chk = QCheckBox("Registrar fecha de nacimiento")
        saved_bd = customer_data.get("birth_date")
        if saved_bd:
            self.birth_date_chk.setChecked(True)
            try:
                from datetime import date as _d
                if isinstance(saved_bd, str):
                    parts = saved_bd.split("-")
                    self.birth_date_input.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
                elif isinstance(saved_bd, _d):
                    self.birth_date_input.setDate(QDate(saved_bd.year, saved_bd.month, saved_bd.day))
            except Exception:
                self.birth_date_input.setDate(QDate(2000, 1, 1))
        else:
            self.birth_date_chk.setChecked(False)
            self.birth_date_input.setDate(QDate(2000, 1, 1))
        self.birth_date_chk.toggled.connect(
            lambda checked: self.birth_date_input.setEnabled(checked)
        )
        self.birth_date_input.setEnabled(self.birth_date_chk.isChecked())

        # Campos de ubicación
        self.province_combo = QComboBox()
        self.province_combo.currentIndexChanged.connect(self.on_province_changed)

        self.canton_combo = QComboBox()
        self.canton_combo.currentIndexChanged.connect(self.on_canton_changed)

        self.district_combo = QComboBox()

        self.neighborhood_input = QLineEdit(customer_data.get("neighborhood", ""))

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

        # ------------------------------------------------------
        # SCROLL AREA PARA FORMULARIO
        # ------------------------------------------------------
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
        left_col.addWidget(self.cedula_status_label)

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

        # ------------------------------------------------------
        # BOTONES SIEMPRE VISIBLES ABAJO
        # ------------------------------------------------------
        self.save_btn = QPushButton("Guardar cambios")
        self.save_btn.clicked.connect(self.save_changes)
        self.save_btn.setStyleSheet("background-color: #0078D4; padding: 6px; border-radius: 5px;")

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("background-color: #444; padding: 6px; border-radius: 5px;")

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(cancel_btn)

        main_layout.addLayout(btn_layout)

        # Cargar provincias y datos guardados
        self.load_provinces()
        self._load_saved_location()
        self._load_saved_activities()

    # ------------------------------------------------------
    # ENVIAR CAMBIOS AL BACKEND
    # ------------------------------------------------------
    def save_changes(self):
        name = self.name_input.text().strip()

        if not name:
            QMessageBox.warning(self, "Error", "El nombre es obligatorio.")
            return

        # Validar email (formato básico si se ingresó)
        email = self.email_input.text().strip()
        if email:
            import re
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                QMessageBox.warning(self, "Error", "El correo electrónico no tiene un formato válido.")
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

        credit_limit_raw = self.credit_limit_input.text().strip()
        try:
            credit_limit = float(credit_limit_raw) if credit_limit_raw else 0.0
        except ValueError:
            QMessageBox.warning(self, "Error", "El límite de crédito debe ser un número válido.")
            return

        # Obtener datos de ubicación
        province_id = self.province_combo.currentData()
        province_name = self.province_combo.currentText() if province_id else None

        canton_id = self.canton_combo.currentData()
        canton_name = self.canton_combo.currentText() if canton_id else None

        district_id = self.district_combo.currentData()
        district_name = self.district_combo.currentText() if district_id else None

        # has_credit_limit y birth_date
        has_credit_limit = self.has_credit_limit_chk.isChecked()

        birth_date = None
        if self.birth_date_chk.isChecked():
            birth_date = self.birth_date_input.date().toString("yyyy-MM-dd")

        payload = {
            "name": name,
            "email": email or None,
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

        url = f"{API['customers']}/{self.customer_data['id']}"
        api_call(
            "put", url, json=payload, headers=headers,
            on_success=self._on_customer_updated,
            on_error=lambda msg: QMessageBox.warning(self, "Error", f"No se pudo actualizar el cliente.\n\n{msg}"),
            on_finished=self._on_save_finished,
        )

    def _on_customer_updated(self, data):
        QMessageBox.information(self, "Éxito", "Cliente actualizado correctamente.")
        self.accept()

    def _on_save_finished(self):
        self.save_btn.setEnabled(True)
        self.save_btn.setText("Guardar cambios")

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

    # ------------------------------------------------------
    # LOOKUP CÉDULA EN HACIENDA
    # ------------------------------------------------------
    def _do_cedula_lookup(self):
        """Se dispara 600ms después de que el usuario deja de escribir."""
        text = self.id_number_input.text().replace("_", "")
        if self.required_length == 0 or len(text) != self.required_length:
            self.cedula_status_label.setText("")
            return

        self.cedula_status_label.setText("🔍 Consultando Hacienda...")
        self.cedula_status_label.setStyleSheet("font-size: 11px; color: #aaa; padding: 2px 0;")

        url = API["lookup_cedula"](text)
        api_call(
            "get", url, headers=_auth_headers(),
            on_success=self._on_cedula_found,
            on_error=self._on_cedula_error,
        )

    def _on_cedula_found(self, response):
        """Callback: datos del contribuyente recibidos de Hacienda."""
        data = response.get("data", {}) if isinstance(response, dict) else {}
        if not data:
            self.cedula_status_label.setText("")
            return

        nombre = data.get("nombre", "")
        tipo_nombre = data.get("tipoIdentificacionNombre", "")
        actividades = data.get("actividades", [])

        # ── Auto-seleccionar tipo de identificación ──
        if tipo_nombre:
            idx = self.id_type_combo.findText(tipo_nombre)
            if idx >= 0:
                self.id_type_combo.blockSignals(True)
                self.id_type_combo.setCurrentIndex(idx)
                self.id_type_combo.blockSignals(False)

        # ── Cargar actividades económicas ──
        if actividades:
            self.activities_list.clear()
            for act in actividades:
                label = f'{act["code"]} - {act["description"][:60]}'
                self.activities_list.addItem(label)

        # ── Mostrar feedback ──
        n_act = len(actividades)
        self.cedula_status_label.setText(
            f"✅ {nombre}  —  {n_act} actividad(es) cargada(s)"
        )
        self.cedula_status_label.setStyleSheet("font-size: 11px; color: #28a745; padding: 2px 0;")

    def _on_cedula_error(self, msg):
        """Callback: error en la consulta."""
        if "404" in msg or "no encontrada" in msg.lower():
            self.cedula_status_label.setText("⚠️ Identificación no encontrada en Hacienda")
            self.cedula_status_label.setStyleSheet("font-size: 11px; color: #ffc107; padding: 2px 0;")
        elif "429" in msg:
            self.cedula_status_label.setText("⏳ Límite de consultas alcanzado, intente en unos minutos")
            self.cedula_status_label.setStyleSheet("font-size: 11px; color: #ffc107; padding: 2px 0;")
        else:
            self.cedula_status_label.setText("")

    # ------------------------------------------------------
    # MÉTODOS PARA UBICACIÓN GEOGRÁFICA
    # ------------------------------------------------------
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

    def _load_saved_location(self):
        """Cargar la ubicación guardada del cliente usando run_async."""
        import requests as _requests
        run_async(
            self._fetch_saved_location_data,
            on_success=self._apply_saved_location,
        )

    def _fetch_saved_location_data(self):
        """Ejecuta en background — NO tocar widgets Qt aquí."""
        import requests as _requests
        result = {"cantons": {}, "districts": {}}
        province_id = self.customer_data.get("province_id")
        canton_id = self.customer_data.get("canton_id")

        if province_id:
            try:
                r = _requests.get(API["cantons"](province_id), headers=_auth_headers(), timeout=10)
                if r.status_code == 200:
                    result["cantons"] = r.json()
            except Exception:
                pass

            if canton_id:
                try:
                    r = _requests.get(API["districts"](province_id, canton_id), headers=_auth_headers(), timeout=10)
                    if r.status_code == 200:
                        result["districts"] = r.json()
                except Exception:
                    pass

        return result

    def _apply_saved_location(self, result):
        """Aplica los datos de ubicación en el hilo principal."""
        self.province_combo.blockSignals(True)
        self.canton_combo.blockSignals(True)
        self.district_combo.blockSignals(True)

        province_id = self.customer_data.get("province_id")
        canton_id = self.customer_data.get("canton_id")
        district_id = self.customer_data.get("district_id")

        if province_id:
            idx = self.province_combo.findData(province_id)
            if idx >= 0:
                self.province_combo.setCurrentIndex(idx)

            # Poblar cantones
            cantons = result.get("cantons", {})
            if cantons:
                self.canton_combo.clear()
                self.canton_combo.addItem("— Seleccione —", None)
                for cid, name in cantons.items():
                    self.canton_combo.addItem(name, cid)

                if canton_id:
                    idx = self.canton_combo.findData(canton_id)
                    if idx >= 0:
                        self.canton_combo.setCurrentIndex(idx)

            # Poblar distritos
            districts = result.get("districts", {})
            if districts:
                self.district_combo.clear()
                self.district_combo.addItem("— Seleccione —", None)
                for did, name in districts.items():
                    self.district_combo.addItem(name, did)

                if district_id:
                    idx = self.district_combo.findData(district_id)
                    if idx >= 0:
                        self.district_combo.setCurrentIndex(idx)

        self.province_combo.blockSignals(False)
        self.canton_combo.blockSignals(False)
        self.district_combo.blockSignals(False)

    # ------------------------------------------------------
    # MÉTODOS PARA ACTIVIDADES ECONÓMICAS
    # ------------------------------------------------------
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

    def _load_saved_activities(self):
        """Cargar las actividades económicas guardadas del cliente (robusto)"""

        # 1) agarrar cualquier variante posible
        raw = (
            self.customer_data.get("economic_activities")
            or self.customer_data.get("activities")
            or self.customer_data.get("economicActivities")
            or []
        )

        normalized = []

        # 2) normalizar a [{"code":..., "description":...}, ...]
        if isinstance(raw, list):
            for a in raw:
                if isinstance(a, str):
                    normalized.append({"code": a})
                    continue

                if isinstance(a, dict):
                    code = (
                        a.get("code")
                        or a.get("activity_code")
                        or a.get("activityCode")
                        or a.get("economic_activities_1_code")        # ✅ alias típico de joins
                        or a.get("economic_activity_code")
                    )
                    desc = (
                        a.get("description")
                        or a.get("activity_description")
                        or a.get("economic_activities_1_description")  # ✅ alias típico de joins
                    )
                    if code:
                        normalized.append({"code": str(code), "description": desc})
                    continue

        # 3) fallback: si viene como codes aparte
        if not normalized:
            codes = (
                self.customer_data.get("economic_activity_codes")
                or self.customer_data.get("economicActivityCodes")
                or self.customer_data.get("activity_codes")
                or []
            )
            if isinstance(codes, list):
                for c in codes:
                    if c:
                        normalized.append({"code": str(c)})

        # 4) pintar
        self.activities_list.clear()

        for activity in normalized:
            code = activity.get("code")
            if not code:
                continue

            description = activity.get("description")
            if description:
                label = f"{code} - {str(description)[:60]}"
                self.activities_list.addItem(label)
                continue

            # si no viene descripción, agregar solo el código
            # (la descripción se buscará al editar)
            self.activities_list.addItem(code)