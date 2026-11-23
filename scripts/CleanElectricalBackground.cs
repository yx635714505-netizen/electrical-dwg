using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.AutoCAD.DatabaseServices;

public static class CleanElectricalBackground
{
    public const string OpeningGeometryLayer = "BASE-门窗";
    private static readonly Regex OpeningCode = new Regex(
        @"^(?:[A-Z]{0,4}[MC][A-Z]{0,2}|DOOR|WINDOW|WIN)[\s_-]*[0-9]{3,6}(?:[A-Z]|[-_]\d{1,3})?$",
        RegexOptions.CultureInvariant | RegexOptions.IgnoreCase);

    public static void Openings(ObjectId background, Transaction transaction)
    {
        CleanBlock(background, transaction, new HashSet<ObjectId>());
    }

    private static void CleanBlock(ObjectId block, Transaction transaction, HashSet<ObjectId> visited)
    {
        if (!visited.Add(block)) return;
        var owner = (BlockTableRecord)transaction.GetObject(block, OpenMode.ForWrite);
        if (owner.IsFromExternalReference || owner.IsFromOverlayReference)
            throw new InvalidOperationException("门窗验收前应将专用底图引用整理为本地块。");
        var entities = owner.Cast<ObjectId>()
            .Select(id => transaction.GetObject(id, OpenMode.ForRead) as Entity)
            .Where(entity => entity != null).ToArray();
        var walls = entities.Where(entity => entity.GetRXClass().DxfName == "TCH_WALL").ToArray();
        var frozenWalls = new List<Entity>();
        if (entities.Any(IsNativeOpening))
        {
            // Capture all wall edges while their original associations still resolve.
            foreach (var wall in walls)
            {
                var geometry = new List<Entity>();
                CollectGeometry(wall, geometry, 0);
                // A wall section fully occupied by a door or covered by columns
                // can have no visible primitives at the current plan cut.
                foreach (var part in geometry)
                    AddFaded(part, wall.Layer, owner, transaction);
                frozenWalls.Add(wall);
            }
        }
        foreach (var entity in entities)
        {
            var reference = entity as BlockReference;
            if (IsNativeOpening(entity) || (reference != null && IsOpeningLayer(entity.Layer)))
            {
                var retained = new List<Entity>();
                CollectGeometry(entity, retained, 0);
                if (retained.Count == 0)
                    throw new InvalidOperationException("未从门窗提取到可见几何，句柄 " + entity.Handle);
                foreach (var part in retained)
                    AddFaded(part, OpeningGeometryLayer, owner, transaction);
                Erase(entity);
                continue;
            }
            if (IsNumber(entity))
            {
                Erase(entity);
                continue;
            }
            if (reference == null) continue;
            foreach (var attributeId in reference.AttributeCollection.Cast<ObjectId>().ToArray())
            {
                var attribute = (AttributeReference)transaction.GetObject(attributeId, OpenMode.ForRead);
                if (IsNumber(attribute)) Erase(attribute);
            }
            CleanBlock(reference.BlockTableRecord, transaction, visited);
        }
        foreach (var wall in frozenWalls) Erase(wall);
    }

    private static bool IsNativeOpening(Entity entity)
    {
        string type = entity.GetRXClass().DxfName;
        return type == "TCH_OPENING" || type == "TCH_DOOR" || type == "TCH_WINDOW";
    }

    private static void AddFaded(Entity entity, string layer, BlockTableRecord owner, Transaction transaction)
    {
        owner.AppendEntity(entity);
        transaction.AddNewlyCreatedDBObject(entity, true);
        entity.Layer = layer;
        entity.ColorIndex = 8;
        entity.LineWeight = LineWeight.LineWeight009;
    }

    private static bool IsOpeningLayer(string layer)
    {
        return layer.IndexOf("WINDOW", StringComparison.OrdinalIgnoreCase) >= 0
            || layer.IndexOf("DOOR", StringComparison.OrdinalIgnoreCase) >= 0
            || layer.Contains("门窗");
    }

    private static bool IsNumber(Entity entity)
    {
        string type = entity.GetRXClass().DxfName;
        string layer = entity.Layer;
        var text = entity as DBText;
        var multiline = entity as MText;
        if (text == null && multiline == null && !type.Contains("TEXT")) return false;
        if (layer.IndexOf("AXIS", StringComparison.OrdinalIgnoreCase) >= 0 || layer.Contains("轴号")) return false;
        if (IsOpeningLayer(layer)) return true;
        if (text != null) return OpeningCode.IsMatch(text.TextString.Trim());
        if (multiline != null) return OpeningCode.IsMatch(multiline.Text.Trim());

        var display = new DBObjectCollection();
        try
        {
            entity.Explode(display);
            return display.Cast<DBObject>().Any(part =>
                part is DBText && OpeningCode.IsMatch(((DBText)part).TextString.Trim()));
        }
        finally
        {
            foreach (DBObject part in display) part.Dispose();
        }
    }

    private static void CollectGeometry(Entity source, List<Entity> geometry, int depth)
    {
        if (depth > 8) throw new InvalidOperationException("门窗显示块嵌套过深。");
        var parts = new DBObjectCollection();
        source.Explode(parts);
        foreach (DBObject obj in parts)
        {
            var nested = obj as BlockReference;
            if (nested != null)
            {
                try { CollectGeometry(nested, geometry, depth + 1); }
                finally { nested.Dispose(); }
            }
            else if (obj is Curve || obj is Hatch || obj is Solid)
                geometry.Add((Entity)obj);
            else
                obj.Dispose();
        }
    }

    private static void Erase(Entity entity)
    {
        if (!entity.IsWriteEnabled) entity.UpgradeOpen();
        entity.Erase();
    }
}
