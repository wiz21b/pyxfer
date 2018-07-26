import io
import unittest
import logging
from unittest import skip
from pprint import pprint, PrettyPrinter

from pyxfer.pyxfer import SQLAWalker, SKIP, generated_code, SQLAAutoGen
from pyxfer.type_support import SQLADictTypeSupport, SQLATypeSupport

logging.getLogger("pyxfer").setLevel(logging.DEBUG)

from sqlalchemy import MetaData, Integer, ForeignKey, Date, Column, Float, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, backref, relationship


metadata = MetaData()
MapperBase = declarative_base(metadata=metadata)

class Operation(MapperBase):
    __tablename__ = 'operations'

    operation_id = Column('operation_id',Integer,autoincrement=True,nullable=False,primary_key=True)

    name = Column('name',String,nullable=False)


class Order(MapperBase):
    __tablename__ = 'orders'

    order_id = Column('order_id',Integer,autoincrement=True,nullable=False,primary_key=True)

    start_date = Column('start_date',Date)
    cost = Column('hourly_cost',Float,nullable=False,default=0)

    parts = relationship('OrderPart', backref=backref('order'))


class OrderPart(MapperBase):
    __tablename__ = 'order_parts'

    order_part_id = Column('order_part_id',Integer,autoincrement=True,nullable=False,primary_key=True)

    order_id = Column('order_id',Integer,ForeignKey( Order.order_id),nullable=False)
    name = Column('name',String,nullable=False)

    operation_id = Column('operation_id',Integer,ForeignKey( Operation.operation_id),nullable=False)
    operation = relationship(Operation, uselist=False)





engine = create_engine("sqlite:///:memory:")
MapperBase.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

def print_code( gencode : str):
    lines = gencode.split("\n")
    for i in range( 1, len( lines)):
        lines[i] = "{:5}: {}".format(i, lines[i])
    print( "\n".join( lines) )


def rename_ids( d, new_id):

    if type(d) == dict:
        if SQLADictTypeSupport.ID_TAG in d:
            id_value = d[SQLADictTypeSupport.ID_TAG]

            if id_value in new_id:
                d[SQLADictTypeSupport.ID_TAG] = new_id[id_value]
            else:
                new_id[id_value] = len(new_id)
                d[SQLADictTypeSupport.ID_TAG] = new_id[id_value]

        for key in sorted( d.keys()):
            rename_ids( d[key], new_id)

    elif type(d) == list:
        for entry in d:
            rename_ids( entry, new_id)

    return d

def canonize_dict( d : dict):
    rename_ids( d, dict())
    s = io.StringIO()
    PrettyPrinter(stream=s).pprint( d)
    return s.getvalue()

class Test(unittest.TestCase):

    @classmethod
    def setUpClass(cls):

        op = Operation()
        op.operation_id = 12
        op.name = "lazer cutting"
        session.add(op)

        o = Order()
        o.hourly_cost = 1.23
        session.add(o)

        p = OrderPart()
        session.add(p)
        p.name = "Part One"
        p.order_id = o.order_id
        o.parts.append(p)
        p.operation = op

        p = OrderPart()
        p.name = "Part Two"
        session.add(p)
        o.parts.append(p)
        p.operation = op

        session.commit()

    #@skip
    def test_happy(self):
        # This is the walker, one of the basic buidling blocks of Pyxfer.
        # The walker's job is to go around a model of the objects
        # to serializer to dtermine the fields and the relationships
        # to work on. With that information, we'll be able to build
        # serializers.

        w = SQLAWalker()

        # Build the type supports for our mappers
        # A type support is a tool class that allows
        # to build the code fragments that will make
        # the serializer source code.
        # The TypeSupport class will be used by
        # the walker to actually generate code.

        order_ts = SQLATypeSupport( Order)
        order_part_ts = SQLATypeSupport( OrderPart)

        # We'll serialize to dict, so we use another
        # type support for that (SQLADict are a bit
        # more clever than regular dicts when it comes
        # to serialization).

        order_dts = SQLADictTypeSupport( Order)
        order_part_dts = SQLADictTypeSupport( OrderPart)

        # Build the serializers. Note that in case of relationship,
        # they must be wired together with the "field_control"

        # Read the following line like this : using a walker, we build
        # a order_part_ser Serializer that will be able to convert
        # from source OrderPart to destination objects dict's.  The
        # names of fields to read in the source objects are given by
        # the OrderPart mapper (the base type). These names will be
        # used both when reading and writing from source to destination
        # objects. Which fields will be seriliaized or not is indicated
        # by the fields_control (SKIP means don't serialize)

        # FIXME What about those fields WE WANT ?
        order_part_ser = w.walk( order_part_ts, OrderPart, order_part_dts,
                                 fields_control= { 'order' : SKIP, 'operation' : SKIP})

        order_ser = w.walk( order_ts, Order, order_dts,
                            fields_control= { 'parts' : order_part_ser})

        # Finally, we can generate the code
        gencode = generated_code( [order_part_ser, order_ser] )

        # It is very useful to read the generated code. We do
        # lots of efforts to make it clear (you can skip the caching
        # stuff first, because it's a bit trickier).
        print_code(gencode)

        # Once you have the code, you can compile/exec it
        # like this or simply save it and import it when needed.
        self.executed_code = dict()
        exec( compile( gencode, "<string>", "exec"), self.executed_code)

        # Now we can serialize
        o = session.query(Order).first()
        assert len(o.parts) == 2

        # Calling is a bit awkward, you must read the generated
        # code to know the name of seriliaztion functions. Note
        # that the names of thosee function follow a regular
        # pattern : walked_type_source type support_destination_type
        # support. If you had imported the code, then you're dev
        # environement would auto complete, which is much easier.

        serialized = self.executed_code['serialize_Order_Order_to_dict']( o, None)
        pprint( serialized)

        session.commit()

        # Once you got it, you can revert the serialization easily
        # Note that you if you use factories, this code can
        # be shared quite a lot.

        order_part_unser = w.walk( order_part_dts, OrderPart, order_part_ts,
                                   fields_control= { 'order' : SKIP, 'operation' : SKIP})

        order_unser = w.walk( order_dts, Order, order_ts,
                              fields_control= { 'parts' : order_part_unser})

        gencode = generated_code( [order_part_unser, order_unser] )
        print_code(gencode)
        self.executed_code = dict()
        exec( compile( gencode, "<string>", "exec"), self.executed_code)

        # Note that when one serializes to SQLAlchemy objects, one
        # needs a SQLA session (because we'll need to add new objects
        # to it).


        unserialized = self.executed_code['serialize_Order_dict_to_Order']( serialized, None, session)
        pprint( unserialized)

        # Note 2 : the serializer we propose is smart enough to reload
        # objects alreay existing in the database. So you can use it
        # update objects rather than to create them.
        assert unserialized.order_id == o.order_id


    def test_autogen(self):

        # First you describe which types will be serialized.  Note
        # that the description of the type itself (fields,
        # relationships) is in fact provided by the SQLAlchemy
        # mappers.  By default, everything gets serializer (you have
        # less control, but less to write too).  You can ask to skip
        # some fileds/relationships in order to avoid unwanted
        # recursion. If you need more control, check the other test
        # cases.

        model_and_field_controls = { Order : {},
                                     Operation : {},
                                     OrderPart : { 'order' : SKIP } }

        # Build serializers to serialize from SQLA objects to dicts
        # The SQLAAutoGen class is just a big shortcut
        # to code generation.
        sqag1 = SQLAAutoGen( SQLATypeSupport, SQLADictTypeSupport, SQLAWalker())
        sqag1.make_serializers( SQLATypeSupport, SQLADictTypeSupport, model_and_field_controls)

        # Build serializers to serialize in the reverse direction
        # Note that we use the very same construction as above,
        # with parameters in a different order.

        sqag2 = SQLAAutoGen( SQLADictTypeSupport, SQLATypeSupport,  SQLAWalker())
        sqag2.make_serializers( SQLADictTypeSupport, SQLATypeSupport, model_and_field_controls)

        # Generate the code of the serializers and compile it.
        # notice we gather all the seriliazers to generate the code
        # this will help the code generator to trim redundant code.

        gencode = generated_code( sqag1.serializers + sqag2.serializers )
        print_code(gencode)
        self.executed_code = dict()
        exec( compile( gencode, "<string>", "exec"), self.executed_code)

        # And of course, let's test it !

        o = session.query(Order).first()
        serialized = self.executed_code['serialize_Order_Order_to_dict']( o, None)


        # This is the expected result. Note the optimisation we do for
        # the "operation" value. The first time it appears, we we give
        # its full value (a normal recursion). But when it appears a
        # second time, we limit ourselves to a key that identifies the
        # previous full value. This way, we won't replicate a dict
        # that appears several times in the serialisation.  That's
        # useful when many objects refer to a few other ones.  In our
        # case, many order parts were refering to a small set of well
        # defined operations. Of course, deserialization has to be
        # smart enough to understand that kind of shortcut (hint : it
        # is :-))

        expected = {'cost': 0.0,
                    'order_id': 1,
                    'parts': [{'name': 'Part One',
                               'operation': {'name': 'lazer cutting', 'operation_id': 12},
                               'operation_id': 12,
                               'order_id': 1,
                               'order_part_id': 1},
                              {'name': 'Part Two',
                               'operation': {'operation_id': 12},
                               'operation_id': 12,
                               'order_id': 1,
                               'order_part_id': 2}],
                    'start_date': None}

        r = canonize_dict( expected)
        s = canonize_dict( serialized)

        print(r)
        print("-"*80)
        print(s)

        assert r == s

if __name__ == "__main__":

    unittest.main()



"""
Not building the latest KDE on Debian Stable

Dear Kde-Devel,

2 or 3 months ago I was super motivated to bring one or two very small
improvements to some KDE components (some small polish here and
there). I looked at the code and thought I was able to do it (I know
Qt, C++ but I'm not much in the make system). So I downloaded KDE and
tried to build it.  I tried for abour 3-4 days to no avail. KDE
wouldn't build because of some small libraries here and there would
stubbornly refuse to build, because of missing dependencies not taken
into account in the build system or documentatio. I tried IRC, read a
lot on the various wiki's (but not this ML), no success. And my setup
was nothing fancy, I just tried to build KDE on Debian latest's stable
(a year old or so).

In case you wonder, things turned very bad when I had to compile
qtwebkit (which is/is not in Qt anymore, it's very unclear to me) and
kwayland because Debian's stable versions are too old; it was
impossible to figure how to build qt5webkit and kde-srcbuild would not
see the wayland/webkit I built. To this day, I still don't know if it
is even possible to build the most recent KDE on Debian stable.

The problem I think lies with kdesrc-build. Its problem is that it
*almost* work. It works like 95%.  But the issue is : kdesrc-build
embodies a very advanced knowledge of KDE and therefore, there seems
to be no one who's able to understand or fix it. So the last 5% just
blocks everything.

I also understand KDE is a volunteer project and that time is scarce
and people prefer to write code than to sort out details of the
build procedure. Been there, done that.

If someone would help me a bit, that'd be fine. And I'd be more than
happy to document my efforts in the various wiki (if I'm sure information
will be made available).

Some more info. When trying to build KDE, you fall there :

>>> https://kdesrc-build.kde.org/
>>> https://docs.kde.org/trunk5/en/extragear-utils/kdesrc-build/index.html
>>> https://community.kde.org/Guidelines_and_HOWTOs/Build_from_source
>>> https://community.kde.org/Guidelines_and_HOWTOs/Build_from_source/Details

this documentation is nice but it completely avoids the question of
what platform one builds on.  And that sounds just wrong since I'm
sure there are many people who build KDE and therefore, there must be
a ton of experience floating around.

Also, during the course of my attempt to build KDE, the build system
was updated 2 or 3 times on git and it was broken once. And of course,
when you don't know that system, the fact it's broken is absolutely not
obvious to you so you spend hours figuring out what's wrong. Could there
be some "stable" snapshots of KDE sources (and a road to upgrade from
there to the latest developement) ?

Now I see :

>>> https://marc.info/?l=kde-devel&m=150804247525359&w=2

wouldn't it be great if kdesrcbuild just said "I won't build Qt5,
please use the Qt5 official release, located at this URL and follow
the instructions at that URL" ? I insist a bit because, for Qt5, things
are not clear neither : which version is OK ? The source one ? the
prebuilt ? For me the source version worked better, but I sure don't
know why.

Overall, my experience is it's very tough to get onboard KDE, because
it's like there amny things that are "assumed" to be known here and there.
And each of these little thing is a little effort that could be avoided
if properly documented. And the sum of the little efforts for these
little things is quite taxing...

Some difficulties I had :

* I had to build Qt5 myself ('cos Debian's is outdated). Which Qt5 version should I use ? I used :

git clone git://code.qt.io/qt/qt5.git
cd qt5
git checkout 5.9
perl init-repository
./configure --prefix=/mnt/data2/kde/qt5git -opensource -release -nomake tests -nomake examples -confirm-license -no-gtk -dbus -no-separate-debug-info -xcb -system-xcb -qpa xcb -release -force-debug-info -reduce-relocations -optimized-qmake -no-gstreamer
make install

Is it correct ? Which one of these fields (gathered from various docs) are actually necessary for a KDE build ?

* Wayland must be upgraded too. I did :

xz -d ~/Downloads/wayland-1.14.91.tar.xz
./configure --prefix=/mnt/data2/kde/wayland --disable-documentation
make
make install

How do I tell kdebuildsrc to use it without installing wayland on my Debian ?

* Should I build qtwebkit ? I did this :

Downlaoded qtwebkit opensource 5.9.0 (is it right ?)
cd qtwebkit-opensource-src-5.9.0
# This was found on the web, dunno exatcly what it does :
sed -e '/CONFIG/a QMAKE_CXXFLAGS += -Wno-expansion-to-defined' \
    -i Tools/qmake/mkspecs/features/unix/default_pre.prf
mkdir -p build
cd build
/mnt/data2/kde/qt5git/bin/qmake ../WebKit.pro
make

Again, how do I tell kdebuildsrc to use it without installing wayland on my Debian ?



Stefan

PS: I'm not blaming anybody, KDE is fantastic and I use it a lot. It's just
it was a very frustrating experience.

PS2: maybe I'm not good enough to build KDE :-( But having written C, C++,
python, java, assembly on the course of 30+ years in start ups, big companies, etc.
should do it, should it ?

"""
