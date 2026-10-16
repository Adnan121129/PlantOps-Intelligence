from __future__ import annotations

from rest_framework import serializers

from .models import Employee, OvertimeRecord, ShiftAssignment, ShiftDefinition, ShiftHandover

CONTACT_FIELDS = ("email", "phone", "hourly_rate")


class EmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    user_name = serializers.CharField(source="user.username", read_only=True, default=None)

    class Meta:
        model = Employee
        fields = ["id", "employee_code", "first_name", "last_name", "full_name", "department", "department_name",
                  "job_title", "employment_status", "email", "phone", "hourly_rate", "user", "user_name"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request is None or not request.user.has_perm_code("employees.view_contact"):
            for field in CONTACT_FIELDS:
                data.pop(field, None)
        return data


class ShiftDefinitionSerializer(serializers.ModelSerializer):
    crosses_midnight = serializers.BooleanField(read_only=True)
    duration_hours = serializers.FloatField(read_only=True)

    class Meta:
        model = ShiftDefinition
        fields = ["id", "plant", "code", "name", "start_time", "end_time", "min_staff", "sequence", "is_active",
                  "crosses_midnight", "duration_hours"]
        validators = [serializers.UniqueTogetherValidator(queryset=ShiftDefinition.objects.all(), fields=["plant", "code"])]

    def validate(self, attrs):
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start == end:
            raise serializers.ValidationError({"end_time": "A shift must have a non-zero duration."})
        return attrs


class ShiftAssignmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_code = serializers.CharField(source="employee.employee_code", read_only=True)
    shift_name = serializers.CharField(source="shift.name", read_only=True)
    plant_unit_code = serializers.CharField(source="plant_unit.code", read_only=True, default=None)

    class Meta:
        model = ShiftAssignment
        fields = ["id", "employee", "employee_name", "employee_code", "shift", "shift_name", "date", "plant_unit",
                  "plant_unit_code", "duty", "notes"]
        validators = [serializers.UniqueTogetherValidator(
            queryset=ShiftAssignment.objects.all(), fields=["employee", "date"],
            message="This employee is already assigned to a shift on this date.")]

    def validate(self, attrs):
        employee = attrs.get("employee", getattr(self.instance, "employee", None))
        shift = attrs.get("shift", getattr(self.instance, "shift", None))
        unit = attrs.get("plant_unit", getattr(self.instance, "plant_unit", None))
        if employee and employee.employment_status != Employee.Status.ACTIVE:
            raise serializers.ValidationError({"employee": "Inactive employees cannot be rostered."})
        if shift and not shift.is_active:
            raise serializers.ValidationError({"shift": "The shift is inactive."})
        if unit and shift and unit.plant_id != shift.plant_id:
            raise serializers.ValidationError({"plant_unit": "The unit belongs to a different plant than the shift."})
        return attrs


class ShiftHandoverSerializer(serializers.ModelSerializer):
    shift_name = serializers.CharField(source="shift.name", read_only=True)
    plant_unit_code = serializers.CharField(source="plant_unit.code", read_only=True)
    handed_over_by_name = serializers.CharField(source="handed_over_by.display_name", read_only=True)
    received_by_name = serializers.CharField(source="received_by.display_name", read_only=True, default=None)

    class Meta:
        model = ShiftHandover
        fields = ["id", "plant_unit", "plant_unit_code", "shift", "shift_name", "date", "summary", "outstanding_issues",
                  "safety_notes", "handed_over_by", "handed_over_by_name", "received_by", "received_by_name",
                  "received_at", "created_at"]
        read_only_fields = ["handed_over_by", "received_by", "received_at"]
        validators = [serializers.UniqueTogetherValidator(
            queryset=ShiftHandover.objects.all(), fields=["plant_unit", "shift", "date"],
            message="A handover for this unit, shift and date already exists.")]

    def validate(self, attrs):
        from django.utils import timezone

        if self.instance is not None and self.instance.received_at is not None:
            raise serializers.ValidationError("Acknowledged handovers cannot be edited.")
        if attrs.get("date") and attrs["date"] > timezone.localdate():
            raise serializers.ValidationError({"date": "Handover date cannot be in the future."})
        unit, shift = attrs.get("plant_unit"), attrs.get("shift")
        if unit and shift and unit.plant_id != shift.plant_id:
            raise serializers.ValidationError({"shift": "The shift belongs to a different plant."})
        return attrs


class OvertimeRecordSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_code = serializers.CharField(source="employee.employee_code", read_only=True)
    work_order_number = serializers.CharField(source="work_order.number", read_only=True, default=None)
    recorded_by_name = serializers.CharField(source="recorded_by.display_name", read_only=True)
    decided_by_name = serializers.CharField(source="decided_by.display_name", read_only=True, default=None)

    class Meta:
        model = OvertimeRecord
        fields = ["id", "employee", "employee_name", "employee_code", "date", "hours", "rate_multiplier", "cost",
                  "reason", "work_order", "work_order_number", "status", "recorded_by", "recorded_by_name",
                  "decided_by", "decided_by_name", "decided_at"]
        read_only_fields = ["cost", "status", "recorded_by", "decided_by", "decided_at"]

    def validate(self, attrs):
        from django.utils import timezone

        if self.instance is not None and self.instance.status != OvertimeRecord.Status.PENDING:
            raise serializers.ValidationError("Decided overtime records cannot be edited.")
        if attrs.get("date") and attrs["date"] > timezone.localdate():
            raise serializers.ValidationError({"date": "Overtime cannot be recorded for a future date."})
        hours = attrs.get("hours")
        if hours is not None and not (0 < hours <= 16):
            raise serializers.ValidationError({"hours": "Overtime hours must be between 0 and 16."})
        if attrs.get("rate_multiplier") is not None and attrs["rate_multiplier"] < 1:
            raise serializers.ValidationError({"rate_multiplier": "The multiplier must be at least 1."})
        return attrs
