using System;
using System.Collections.Generic;
using System.Linq;

// Include with the native job plugin. Use only for plotting, never for creating layouts.
public static class ElectricalPlotBatch
{
    public sealed class Page<T>
    {
        public readonly T Sheet;
        public readonly bool Color;
        public readonly bool Monochrome;

        internal Page(T sheet, bool color, bool monochrome)
        {
            Sheet = sheet;
            Color = color;
            Monochrome = monochrome;
        }
    }

    // A final pass preserves both existing plot variants on every layout.
    public static List<Page<T>> Final<T>(IEnumerable<T> sheets, Func<T, string> number)
    {
        return Select(sheets, number, null, true, true);
    }

    // A null scope means all pages (unknown impact). A known scope must be nonempty.
    public static List<Page<T>> Preview<T>(IEnumerable<T> sheets, Func<T, string> number,
        IEnumerable<string> affectedNumbers, bool color, bool monochrome)
    {
        return Select(sheets, number, affectedNumbers, color, monochrome);
    }

    private static List<Page<T>> Select<T>(IEnumerable<T> sheets, Func<T, string> number,
        IEnumerable<string> affectedNumbers, bool color, bool monochrome)
    {
        if (!color && !monochrome)
            throw new ArgumentException("Select at least one plot variant.");
        var requested = affectedNumbers == null ? null : new HashSet<string>(affectedNumbers);
        if (requested != null && requested.Count == 0)
            throw new ArgumentException("Empty affected page list. Use null for the full set.");
        var seen = new HashSet<string>();
        var pages = new List<Page<T>>();
        foreach (T sheet in sheets)
        {
            string id = number(sheet);
            if (String.IsNullOrWhiteSpace(id) || !seen.Add(id))
                throw new ArgumentException("Missing or repeated sheet number: " + id);
            if (requested == null || requested.Remove(id))
                pages.Add(new Page<T>(sheet, color, monochrome));
        }
        if (seen.Count == 0)
            throw new ArgumentException("No sheets to plot.");
        if (requested != null && requested.Count != 0)
            throw new ArgumentException("Unknown sheet numbers: " + String.Join(", ", requested));
        return pages;
    }
}
